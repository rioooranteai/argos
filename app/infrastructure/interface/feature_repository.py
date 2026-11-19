"""Port penyimpanan hasil pemrosesan satu versi dokumen (bagian + features)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.extraction.model import FeatureRow
from app.services.ingestion.model import Section


class BaseFeatureRepository(ABC):
    @abstractmethod
    def publish_version(
        self,
        document_id: str,
        version_id: str,
        sections: list[Section],
        features: list[FeatureRow],
    ) -> bool:
        """Dalam SATU transaksi: tulis bagian & features, tandai versi `ready`, dan
        perbarui `latest_version_id` dokumen. Sebelum ini selesai, tidak ada data
        versi yang terlihat oleh chat.

        Return False (tanpa menulis apa pun) jika pembatalan sudah diminta.
        """

    @abstractmethod
    def delete_version_content(self, version_id: str) -> None:
        """Hapus bagian & features milik versi (pembersihan data setengah jadi)."""
