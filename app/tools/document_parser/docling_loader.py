import gc
import io
import logging
import threading

import tiktoken
from docling.chunking import HybridChunker
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings as docling_settings
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

from app.core.config import app_config, infra
from app.tools.document_parser.base import (
    BaseDocumentLoader,
    DocumentElement,
    DocumentLoadError,
    ElementType,
)

logger = logging.getLogger(__name__)

# Images whose shortest side (px, images_scale=1.0 ≈ 72 dpi) is below this are treated
# as logos/icons and are not sent to the Vision API.
MIN_FIGURE_SIDE_PX = 100

_DEVICE_MAP = {
    "auto": AcceleratorDevice.AUTO,
    "cuda": AcceleratorDevice.CUDA,
    "gpu": AcceleratorDevice.CUDA,
    "cpu": AcceleratorDevice.CPU,
    "mps": AcceleratorDevice.MPS,
}


def _resolve_device(name: str) -> AcceleratorDevice:
    """Turn DOCLING_DEVICE into an AcceleratorDevice, falling back to CPU when CUDA is missing."""
    key = (name or "auto").strip().lower()
    device = _DEVICE_MAP.get(key)
    if device is None:
        logger.warning("Unknown DOCLING_DEVICE=%r, using 'auto'.", name)
        device = AcceleratorDevice.AUTO

    try:
        import torch

        cuda_ok = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if cuda_ok else None
    except Exception:  # noqa: BLE001 — torch is optional; without torch/CUDA it runs on CPU
        cuda_ok, gpu_name = False, None

    if device == AcceleratorDevice.CUDA and not cuda_ok:
        logger.warning("DOCLING_DEVICE=cuda but CUDA is not available — switching to CPU.")
        device = AcceleratorDevice.CPU

    if device == AcceleratorDevice.CUDA or (device == AcceleratorDevice.AUTO and cuda_ok):
        logger.info("Docling is using the GPU: %s", gpu_name)
    elif device == AcceleratorDevice.AUTO:
        logger.info("Docling auto mode: no CUDA detected, using CPU.")
    else:
        logger.info("Docling is using device: %s", device.value)
    return device


# Page failures caused by the machine (memory, GPU) rather than by the document.
_MACHINE_ERRORS = (
    "bad_alloc", "out of memory", "memoryerror", "unable to allocate", "cuda", "paging file", "os error 1455",
)


class IncompleteConversion(RuntimeError):
    """Docling dropped pages because the machine ran out of memory or the GPU failed.

    The message names the cause so the parser process reports it as a temporary system failure
    (the job is retried) instead of publishing a document with pages silently missing.
    """


def _error_messages(result) -> list[str]:
    return [str(e.error_message) for e in (result.errors or [])]


def _machine_failure(result) -> bool:
    """Did Docling drop pages because of the machine (memory, GPU) rather than the document?"""
    if result.status == ConversionStatus.SUCCESS:
        return False
    return any(m in msg.lower() for msg in _error_messages(result) for m in _MACHINE_ERRORS)


def _check_complete(result, file_path: str) -> None:
    """Never accept a conversion with silently dropped pages."""
    if result.status == ConversionStatus.SUCCESS:
        return
    messages = _error_messages(result)
    if _machine_failure(result):
        raise IncompleteConversion(
            f"system failure while converting {file_path}: {len(messages)} page/stage error(s), "
            f"e.g. {messages[0][:150]}"
        )
    if result.status != ConversionStatus.PARTIAL_SUCCESS:  # FAILURE etc.: the document itself
        raise RuntimeError(f"conversion {result.status.value}: {'; '.join(messages[:3]) or 'no details'}")
    if result.status == ConversionStatus.PARTIAL_SUCCESS:
        logger.warning("Docling converted %s only partially (%d error(s)): %s",
                       file_path, len(messages), "; ".join(messages[:3]))


class DoclingLoader(BaseDocumentLoader):
    """
    PDF loader with HybridChunker and image extraction.
    The device (GPU/CPU) is set by the DOCLING_DEVICE environment variable (default: auto).
    """

    def __init__(self):
        docling_settings.perf.page_batch_size = app_config.DOCLING_PAGE_BATCH_SIZE
        accel_options = AcceleratorOptions(
            device=_resolve_device(infra.DOCLING_DEVICE),
            num_threads=app_config.DOCLING_NUM_THREADS,
        )

        pipeline_options = PdfPipelineOptions()
        # OCR is only needed for scanned PDFs. Images/charts are already read by
        # OpenAI Vision, so for digital PDFs OCR only adds time.
        pipeline_options.do_ocr = app_config.DOCLING_OCR
        pipeline_options.accelerator_options = accel_options
        pipeline_options.generate_picture_images = True
        pipeline_options.images_scale = 1.0

        self.converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.MD],
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )
        self._pipeline_options = pipeline_options
        self._fallback_converter: DocumentConverter | None = None  # built on first need

        encoding = tiktoken.get_encoding("cl100k_base")

        tokenizer = OpenAITokenizer(
            tokenizer=encoding,
            max_tokens=app_config.OPENAI_EMBEDDING_CHUNK_SIZE
        )

        self.chunker = HybridChunker(
            tokenizer=tokenizer,
            merge_peers=True
        )

        self._convert_lock = threading.Lock()

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith((".pdf", ".docx", ".md"))

    def _fallback(self) -> DocumentConverter | None:
        """The converter with the PDF backend from DOCLING_FALLBACK_BACKEND (None = disabled)."""
        name = (app_config.DOCLING_FALLBACK_BACKEND or "").strip().lower()
        if not name:
            return None
        if name != "pypdfium2":
            logger.warning("Unknown DOCLING_FALLBACK_BACKEND=%r; no second attempt.", name)
            return None
        if self._fallback_converter is None:
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

            self._fallback_converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF],
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=self._pipeline_options, backend=PyPdfiumDocumentBackend
                    )
                },
            )
        return self._fallback_converter

    def _convert(self, file_path: str):
        """Convert with the default backend; on a memory failure, once more with the fallback."""
        result = self.converter.convert(file_path, raises_on_error=False)
        if not (file_path.lower().endswith(".pdf") and _machine_failure(result)):
            return result
        fallback = self._fallback()
        if fallback is None:
            return result
        messages = _error_messages(result)
        logger.warning(
            "Docling (default backend) ran out of memory on %s (%d page/stage error(s), e.g. %s); "
            "converting again with the %s backend.",
            file_path, len(messages), messages[0][:120], app_config.DOCLING_FALLBACK_BACKEND,
        )
        del result
        gc.collect()  # release the failed attempt's pages before the second one
        return fallback.convert(file_path, raises_on_error=False)

    def load(self, file_path: str) -> list[DocumentElement]:
        elements: list[DocumentElement] = []

        try:
            # One shared converter; a lock stops parallel uploads from using the
            # same model at the same time (safe for GPU memory).
            with self._convert_lock:
                result = self._convert(file_path)
            _check_complete(result, file_path)
            doc = result.document

            docling_chunks = list(self.chunker.chunk(dl_doc=doc))

            for c in docling_chunks:
                enriched_text = self.chunker.contextualize(chunk=c)
                current_heading = c.meta.headings[-1] if c.meta.headings else ""

                page_num = 0
                if c.meta.doc_items and c.meta.doc_items[0].prov:
                    page_num = c.meta.doc_items[0].prov[0].page_no

                is_table = any(item.label == "table" for item in c.meta.doc_items)

                if not is_table and len(enriched_text) < 15:
                    continue

                el_type = ElementType.TABLE if is_table else ElementType.TEXT

                elements.append(
                    DocumentElement(
                        element_type=el_type,
                        content=enriched_text.strip(),
                        page_number=page_num,
                        section_heading=current_heading,
                        # The full heading path: used to group sections
                        # & extraction units (DESIGN_GROUP_B.md §7).
                        metadata={"headings": list(c.meta.headings or [])},
                    )
                )

            if hasattr(doc, 'pictures'):
                for idx, pic in enumerate(doc.pictures):
                    page_num = pic.prov[0].page_no if pic.prov else 0

                    try:
                        pil_image = pic.get_image(doc)
                        # Small logos/icons hold no data → do not send them to
                        # OpenAI Vision (saves cost & time).
                        if pil_image and min(pil_image.size) < MIN_FIGURE_SIDE_PX:
                            logger.debug(f"Image {idx + 1} on p. {page_num} is too small {pil_image.size}, skipped.")
                            continue
                        if pil_image:
                            img_byte_arr = io.BytesIO()
                            pil_image.save(img_byte_arr, format='PNG')
                            image_bytes = img_byte_arr.getvalue()

                            elements.append(
                                DocumentElement(
                                    element_type=ElementType.FIGURE,
                                    content=f"[IMAGE/CHART {idx + 1}] Waiting for the Vision API...",
                                    page_number=page_num,
                                    section_heading="",
                                    image_bytes=image_bytes,
                                    metadata={},
                                )
                            )
                    except Exception:
                        # One broken image does not fail the document; the text is still processed.
                        logger.warning(
                            "Failed to extract an image on page %s.", page_num, exc_info=True
                        )

            return elements

        except Exception as e:
            raise DocumentLoadError(file_path, f"Docling failed to process the document: {str(e)}") from e
