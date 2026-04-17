import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseExtractionProvider(ABC):

    @abstractmethod
    async def extract(self, text: str) -> list:
        """
        Menerima combined text dari dokumen,
        mengembalikan list hasil ekstraksi (misal list[CompetitorFeature]).
        """
        ...