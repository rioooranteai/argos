from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.notebook.model import ActiveSource, Notebook, NotebookSource


class SourceLimitReached(Exception):
    """The notebook has reached its source limit."""


class BaseNotebookRepository(ABC):
    @abstractmethod
    def create(self, notebook_id: str, owner_id: str, title: str) -> Notebook: ...

    @abstractmethod
    def get(self, notebook_id: str, owner_id: str) -> Notebook | None:
        """None when missing or not owned by `owner_id`."""

    @abstractmethod
    def list_for_owner(self, owner_id: str) -> list[tuple[Notebook, int]]:
        """The user's notebooks with their source counts, newest first."""

    @abstractmethod
    def rename(self, notebook_id: str, title: str) -> None: ...

    @abstractmethod
    def delete(self, notebook_id: str) -> None: ...

    @abstractmethod
    def touch(self, notebook_id: str) -> None: ...

    @abstractmethod
    def mark_opened(self, notebook_id: str) -> None:
        """Record when the notebook was opened (replaces localStorage in the browser)."""

    @abstractmethod
    def list_sources(self, notebook_id: str) -> list[NotebookSource]: ...

    @abstractmethod
    def add_source(self, notebook_id: str, document_id: str, version_id: str, max_sources: int) -> bool:
        """Atomically add a source (the limit is checked in the same transaction).

        Returns False when the document is already in the notebook.
        Raises SourceLimitReached when the notebook is full.
        """

    @abstractmethod
    def set_enabled(self, notebook_id: str, document_id: str, enabled: bool) -> bool: ...

    @abstractmethod
    def set_version(self, notebook_id: str, document_id: str, version_id: str) -> bool: ...

    @abstractmethod
    def remove_source(self, notebook_id: str, document_id: str) -> bool: ...

    @abstractmethod
    def count_version_pins(self, version_id: str) -> int:
        """Number of notebooks (any) that pin this version."""

    @abstractmethod
    def active_sources(self, notebook_id: str) -> list[ActiveSource]:
        """Checked sources whose version is `ready`, in the order they were added."""
