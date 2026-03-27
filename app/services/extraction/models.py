from pydantic import BaseModel, Field
from typing import Optional

class CompetitorFeature(BaseModel):
    """
    Skema data untuk hasil ekstraksi Agent.
    Deskripsi pada Field() ini SANGAT PENTING karena akan dibaca oleh LLM (PydanticAI)
    sebagai instruksi cara mengekstrak datanya.
    """
    competitor_name: str = Field(
        description="Nama perusahaan atau entitas kompetitor (contoh: Tencent Games, NetEase, dll)."
    )
    feature_name: str = Field(
        description="Nama fitur produk, layanan, atau metrik spesifik yang sedang dibahas."
    )
    price: Optional[str] = Field(
        default=None,
        description="Harga atau nilai moneter dari fitur/layanan tersebut. Biarkan null jika tidak disebutkan dalam teks."
    )
    pros_cons: Optional[str] = Field(
        default=None,
        description="Kelebihan (pros) atau kekurangan (cons) dari fitur ini jika ada opini atau evaluasi di dalam teks."
    )