import logging
from typing import Any
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import InputFormat
from app.services.ingestion.base.loader import BaseDocumentLoader
from app.services.ingestion.models import DocumentElement, ElementType
from app.services.ingestion.exceptions import DocumentLoadError

logger = logging.getLogger(__name__)


class DoclingLoader(BaseDocumentLoader):
    """
    Loader PDF berbasis AI menggunakan Docling.
    Sangat kuat untuk membaca multi-column layout, tabel, dan mengekstrak gambar/grafik.
    """

    def __init__(self):
        # Inisialisasi converter. Akan memuat model layout di background.
        self.converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF, InputFormat.DOCX, InputFormat.MD]
        )

    def supports(self, file_path: str) -> bool:
        return file_path.lower().endswith((".pdf", ".docx", ".md"))

    def load(self, file_path: str) -> list[DocumentElement]:
        elements: list[DocumentElement] = []

        try:
            logger.info(f"Memulai Docling parsing untuk: {file_path}")
            # Proses konversi dokumen
            result = self.converter.convert(file_path)
            doc = result.document

            # Variabel untuk menyimpan konteks bab saat ini
            current_heading = ""

            # docling menyimpan elemen dalam urutan baca manusia (reading order)
            for item in doc.texts:
                page_num = item.prov[0].page_no if item.prov else 0

                # 1. Tangkap Heading untuk Konteks
                if item.label == "section_header" or item.label == "title":
                    current_heading = item.text.strip()
                    elements.append(
                        DocumentElement(
                            element_type=ElementType.HEADING,
                            content=current_heading,
                            page_number=page_num,
                            section_heading=current_heading,
                            metadata={"source": file_path, "docling_label": item.label}
                        )
                    )

                # 2. Tangkap Teks Paragraf Biasa
                elif item.label in ["text", "paragraph", "list_item"]:
                    el_type = ElementType.LIST_ITEM if item.label == "list_item" else ElementType.TEXT
                    elements.append(
                        DocumentElement(
                            element_type=el_type,
                            content=item.text.strip(),
                            page_number=page_num,
                            section_heading=current_heading,
                            metadata={"source": file_path}
                        )
                    )

            # 3. Tangkap Tabel (Sangat krusial untuk ekstraksi harga/fitur)
            for table in doc.tables:
                page_num = table.prov[0].page_no if table.prov else 0
                # Export tabel langsung jadi Markdown agar mudah dibaca LLM nanti
                table_md = table.export_to_markdown()
                elements.append(
                    DocumentElement(
                        element_type=ElementType.TABLE,
                        content=table_md,
                        page_number=page_num,
                        section_heading=current_heading,
                        metadata={"source": file_path}
                    )
                )

            # 4. Tangkap Gambar / Grafik (Figures)
            for pic in doc.pictures:
                page_num = pic.prov[0].page_no if pic.prov else 0

                # Docling bisa mengambil ekstrak gambar, tapi butuh setup tambahan
                # (image_export options). Untuk sekarang kita beri placeholder.
                # Nanti kita bisa gunakan PyMuPDF murni HANYA untuk mengambil byte gambar
                # di halaman koordinat yang ditemukan Docling jika dibutuhkan.
                elements.append(
                    DocumentElement(
                        element_type=ElementType.FIGURE,
                        content=f"Terdapat gambar/grafik di dokumen pada bab: {current_heading}.",
                        page_number=page_num,
                        section_heading=current_heading,
                        metadata={"source": file_path, "bbox": pic.prov[0].bbox if pic.prov else None}
                    )
                )

            logger.info(f"Berhasil mengekstrak {len(elements)} elemen dari {file_path}")
            return elements

        except Exception as e:
            raise DocumentLoadError(file_path, f"Docling gagal memproses dokumen: {str(e)}")