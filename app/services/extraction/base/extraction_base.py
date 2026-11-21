import logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class BaseExtractionProvider(ABC):

    @abstractmethod
    async def extract(self, text: str) -> list:
        """
        Takes the combined text of a document and
        returns the extraction results (e.g. list[CompetitorFeature]).
        """
        ...