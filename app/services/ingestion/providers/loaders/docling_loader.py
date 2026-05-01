import io
import logging

import tiktoken
from app.core.config import config
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


class DoclingLoader(BaseDocumentLoader):
    """
    Loader PDF Ultimate dengan akselerasi GPU, HybridChunker, dan Image Extraction.
    """

    def __init__(self):
        accel_options = AcceleratorOptions(
            device=AcceleratorDevice.CUDA,
            num_threads=4
        )

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = True
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
            max_tokens=config.OPENAI_EMBEDDING_CHUNK_SIZE
        )

        self.chunker = HybridChunker(
            tokenizer=tokenizer,
            merge_peers=True
        )

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith((".pdf", ".docx", ".md"))

    def load(self, file_path: str) -> list[DocumentElement]:
        elements: list[DocumentElement] = []

        try:
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
                        metadata={"source": file_path, "docling_strategy": "HybridChunker"}
                    )
                )

            if hasattr(doc, 'pictures'):
                for idx, pic in enumerate(doc.pictures):
                    page_num = pic.prov[0].page_no if pic.prov else 0

                    try:
                        pil_image = pic.get_image(doc)
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
                                    metadata={"source": file_path, "bbox": pic.prov[0].bbox if pic.prov else None}
                                )
                            )
                    except Exception as img_err:
                        logger.warning(f"Gagal mengekstrak gambar di halaman {page_num}: {img_err}")

            return elements

        except Exception as e:
            raise DocumentLoadError(file_path, f"Docling gagal memproses dokumen: {str(e)}") from None
