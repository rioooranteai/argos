import io
import logging
import threading

import tiktoken
from app.core.config import app_config, infra
from app.services.ingestion.base.loader import BaseDocumentLoader
from app.services.ingestion.exceptions import DocumentLoadError
from app.services.ingestion.model import DocumentElement, ElementType
from docling.chunking import HybridChunker
from docling.datamodel.accelerator_options import AcceleratorOptions, AcceleratorDevice
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

logger = logging.getLogger(__name__)

# Sisi terpendek gambar (px, images_scale=1.0 ≈ 72 dpi) di bawah ini dianggap
# logo/ikon dan tidak dikirim ke Vision API.
MIN_FIGURE_SIDE_PX = 100

_DEVICE_MAP = {
    "auto": AcceleratorDevice.AUTO,
    "cuda": AcceleratorDevice.CUDA,
    "gpu": AcceleratorDevice.CUDA,
    "cpu": AcceleratorDevice.CPU,
    "mps": AcceleratorDevice.MPS,
}


def _resolve_device(name: str) -> AcceleratorDevice:
    """Ubah nilai DOCLING_DEVICE jadi AcceleratorDevice, turun ke CPU kalau CUDA tidak ada."""
    key = (name or "auto").strip().lower()
    device = _DEVICE_MAP.get(key)
    if device is None:
        logger.warning("DOCLING_DEVICE=%r tidak dikenal, memakai 'auto'.", name)
        device = AcceleratorDevice.AUTO

    try:
        import torch

        cuda_ok = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if cuda_ok else None
    except Exception:  # noqa: BLE001 — torch opsional; tanpa torch/CUDA = jalan di CPU
        cuda_ok, gpu_name = False, None

    if device == AcceleratorDevice.CUDA and not cuda_ok:
        logger.warning("DOCLING_DEVICE=cuda tapi CUDA tidak tersedia — beralih ke CPU.")
        device = AcceleratorDevice.CPU

    if device == AcceleratorDevice.CUDA or (device == AcceleratorDevice.AUTO and cuda_ok):
        logger.info("Docling memakai GPU: %s", gpu_name)
    elif device == AcceleratorDevice.AUTO:
        logger.info("Docling mode auto: CUDA tidak terdeteksi, memakai CPU.")
    else:
        logger.info("Docling memakai device: %s", device.value)
    return device


class DoclingLoader(BaseDocumentLoader):
    """
    Loader PDF dengan HybridChunker dan Image Extraction.
    Device (GPU/CPU) diatur lewat DOCLING_DEVICE di .env (default: auto).
    """

    def __init__(self):
        accel_options = AcceleratorOptions(
            device=_resolve_device(infra.DOCLING_DEVICE),
            num_threads=app_config.DOCLING_NUM_THREADS,
        )

        pipeline_options = PdfPipelineOptions()
        # OCR hanya perlu untuk PDF hasil scan. Gambar/grafik sudah dibaca oleh
        # OpenAI Vision, jadi untuk PDF digital OCR hanya menambah waktu.
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

    def load(self, file_path: str) -> list[DocumentElement]:
        elements: list[DocumentElement] = []

        try:
            # Satu converter dipakai bersama; kunci agar upload paralel tidak
            # memakai model yang sama secara bersamaan (aman untuk memori GPU).
            with self._convert_lock:
                result = self.converter.convert(file_path)
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
                        # Jalur heading lengkap: dipakai untuk mengelompokkan bagian
                        # & unit ekstraksi (DESIGN_GROUP_B.md §7).
                        metadata={"headings": list(c.meta.headings or [])},
                    )
                )

            if hasattr(doc, 'pictures'):
                for idx, pic in enumerate(doc.pictures):
                    page_num = pic.prov[0].page_no if pic.prov else 0

                    try:
                        pil_image = pic.get_image(doc)
                        # Logo/ikon kecil tidak berisi data → jangan dikirim ke
                        # OpenAI Vision (hemat biaya & waktu).
                        if pil_image and min(pil_image.size) < MIN_FIGURE_SIDE_PX:
                            logger.debug(f"Gambar {idx + 1} hal. {page_num} terlalu kecil {pil_image.size}, dilewati.")
                            continue
                        if pil_image:
                            img_byte_arr = io.BytesIO()
                            pil_image.save(img_byte_arr, format='PNG')
                            image_bytes = img_byte_arr.getvalue()

                            elements.append(
                                DocumentElement(
                                    element_type=ElementType.FIGURE,
                                    content=f"[GAMBAR/GRAFIK {idx + 1}] Menunggu diproses oleh Vision API...",
                                    page_number=page_num,
                                    section_heading="",
                                    image_bytes=image_bytes,
                                    metadata={},
                                )
                            )
                    except Exception:
                        # Satu gambar rusak tidak menggagalkan dokumen; teks tetap diproses.
                        logger.warning(
                            "Gagal mengekstrak gambar di halaman %s.", page_num, exc_info=True
                        )

            return elements

        except Exception as e:
            raise DocumentLoadError(file_path, f"Docling gagal memproses dokumen: {str(e)}") from e
