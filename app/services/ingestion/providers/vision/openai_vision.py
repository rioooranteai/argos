import base64
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

from app.core.config import Config
from app.services.ingestion.base.vision import BaseVisionProcessor
from app.services.ingestion.models import DocumentElement, ElementType
from app.services.ingestion.exceptions import VisionProcessingError

logger = logging.getLogger(__name__)


class OpenAIVisionProcessor(BaseVisionProcessor):
    """
    Memproses ekstraksi visual dari gambar ke teks menggunakan model OpenAI Vision
    secara asynchronous agar tidak memblokir pipeline utama.
    """

    def __init__(self):
        try:
            self.vision_model = ChatOpenAI(
                model=Config.OPENAI_LLM_MODEL,
                api_key=Config.OPENAI_API_KEY,
                temperature=0.0,  # Wajib 0 agar tidak berhalusinasi saat membaca data kompetitor
                max_tokens=1000
            )
        except Exception as e:
            logger.error(f"Gagal inisialisasi OpenAI Vision: {str(e)}")
            raise

    def supports(self, element: DocumentElement) -> bool:
        """Hanya memproses elemen berjenis FIGURE yang memiliki byte gambar."""
        return (
                element.element_type == ElementType.FIGURE
                and element.image_bytes is not None
        )

    async def describe_image(self, element: DocumentElement) -> str:
        """
        Kirim gambar ke OpenAI dan eksekusi secara async (ainvoke).
        """
        if not self.supports(element):
            return ""

        try:
            # 1. Konversi byte gambar mentah ke Base64
            base64_image = base64.b64encode(element.image_bytes).decode("utf-8")

            # 2. Sisipkan konteks bab jika ada (Sangat membantu AI memahami grafik)
            context_prompt = ""
            if element.section_heading:
                context_prompt = f"\nKonteks Dokumen: Gambar ini berada di bawah bab/judul '{element.section_heading}'."

            # 3. Prompt Sistem Khusus Competitive Intelligence
            system_instruction = (
                "Kamu adalah analis data kompetitor tingkat lanjut. "
                "Tugasmu adalah mendeskripsikan gambar, grafik, atau tabel visual ini secara detail. "
                "Pastikan kamu mengekstrak elemen-elemen berikut jika ada: "
                "1. Angka pasti (harga, persentase, pangsa pasar, jumlah pengguna). "
                "2. Label sumbu (X/Y) atau nama kategori pada grafik. "
                "3. Tren visual (misal: 'pendapatan meningkat tajam di Q3'). "
                "4. Nama kompetitor atau produk yang disebutkan. "
                f"{context_prompt}\n"
                "Berikan output langsung dalam format paragraf teks yang padat dan informatif."
            )

            message = HumanMessage(
                content=[
                    {"type": "text", "text": system_instruction},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}},
                ]
            )

            logger.info(f"Mengirim gambar (halaman {element.page_number}) ke Vision API secara async...")

            # 4. Gunakan ainvoke() untuk eksekusi Asynchronous
            response = await self.vision_model.ainvoke([message])

            return response.content.strip()

        except Exception as e:
            logger.error(f"Error Vision API di halaman {element.page_number}: {str(e)}")
            # Lemparkan exception custom sesuai kontrakmu
            raise VisionProcessingError(
                page_number=element.page_number,
                reason=str(e)
            )