"""Shared fake tools for tests (DESIGN_GROUP_E.md §3.8).

Every fake inherits the real ``Base…`` contract from ``app/tools``. If a contract gains a
new abstract method, creating the fake fails with ``TypeError: Can't instantiate abstract
class`` — no test keeps passing against an outdated fake.

Inject them exactly like the real tools: through the constructor of the service, engine
or pipeline under test.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence

from pydantic import BaseModel

from app.tools.document_parser.base import BaseDocumentParser, DocumentElement
from app.tools.embedding.base import BaseEmbedder
from app.tools.extraction.base import BaseExtractor, ExtractedFeature
from app.tools.llm.base import BaseLLM
from app.tools.speech.base import BaseSTT, BaseTTS, STTRequest, STTResult, TTSRequest, TTSResult
from app.tools.vector_store.base import AddChunksResult, BaseVectorStore, IndexChunk, SearchHit
from app.tools.vision.base import BaseVisionModel


class FakeLLM(BaseLLM):
    """Answers with fixed text, or with queued responses one per call.

    ``FakeLLM("text")`` always returns "text"; ``FakeLLM(["a", "b"])`` returns "a", then "b".
    ``error`` is raised on every call instead.
    """

    def __init__(self, responses: str | Sequence[str] = "ok", error: BaseException | None = None):
        self._fixed = responses if isinstance(responses, str) else None
        self._queue = [] if isinstance(responses, str) else list(responses)
        self.error = error
        self.calls: list[dict[str, str | None]] = []

    @property
    def response(self) -> str | None:
        """The fixed answer; assign to change it during a test."""
        return self._fixed

    @response.setter
    def response(self, value: str) -> None:
        self._fixed = value

    @property
    def prompts(self) -> list[str]:
        return [c["prompt"] for c in self.calls]

    @property
    def last_prompt(self) -> str | None:
        return self.calls[-1]["prompt"] if self.calls else None

    @property
    def last_system(self) -> str | None:
        return self.calls[-1]["system"] if self.calls else None

    def _answer(self, prompt: str, system: str | None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        if self.error is not None:
            raise self.error
        return self._fixed if self._fixed is not None else self._queue.pop(0)

    def invoke(self, prompt: str, system: str | None = None) -> str:
        return self._answer(prompt, system)

    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        return self._answer(prompt, system)

    def with_structured_output(self, schema: type[BaseModel]) -> BaseLLM:
        return self


class FakeEmbedder(BaseEmbedder):
    """A tiny deterministic embedding: one dimension per keyword, plus a constant."""

    def __init__(self, keywords: Sequence[str] = ("avanza", "honda")):
        self.keywords = [k.lower() for k in keywords]

    def _vec(self, text: str) -> list[float]:
        lowered = text.lower()
        return [float(k in lowered) for k in self.keywords] + [1.0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    @property
    def dimension(self) -> int:
        return len(self.keywords) + 1


class FakeVectorStore(BaseVectorStore):
    """In-memory store. ``search`` returns ``hits`` (or raises ``error``)."""

    def __init__(self, hits: Sequence[SearchHit] = (), error: BaseException | None = None):
        self.hits = list(hits)
        self.error = error
        self.chunks: dict[str, dict] = {}    # chunk_id → metadata
        self.texts: dict[str, str] = {}      # chunk_id → text
        self.embedded: list[str] = []        # texts that would have gone to the embedding API
        self.deleted: list[str] = []         # version_ids passed to delete_version
        self.searches: list[tuple[str, list[str] | None]] = []

    @property
    def called(self) -> bool:
        return bool(self.searches)

    def add_chunks(self, chunks: list[IndexChunk], reuse: Mapping[str, str] | None = None) -> AddChunksResult:
        reuse = reuse or {}
        reused = 0
        for c in chunks:
            if c.text in reuse and reuse[c.text] in self.chunks:
                reused += 1
            else:
                self.embedded.append(c.text)
            self.chunks[c.chunk_id] = c.metadata
            self.texts[c.chunk_id] = c.text
        return AddChunksResult(ids=[c.chunk_id for c in chunks], reused=reused)

    def version_texts(self, version_id: str) -> dict[str, str]:
        return {self.texts[k]: k for k, m in self.chunks.items() if m.get("version_id") == version_id}

    def search(self, query: str, version_ids: list[str] | None, limit: int = 5) -> list[SearchHit]:
        self.searches.append((query, version_ids))
        if self.error is not None:
            raise self.error
        return self.hits[:limit]

    def delete_version(self, version_id: str) -> None:
        self.deleted.append(version_id)
        self.chunks = {k: m for k, m in self.chunks.items() if m.get("version_id") != version_id}

    def count_version(self, version_id: str) -> int:
        return sum(1 for m in self.chunks.values() if m.get("version_id") == version_id)

    def heartbeat(self) -> None:
        if self.error is not None:
            raise self.error


class FakeParser(BaseDocumentParser):
    """Returns a copy of the given elements for every document."""

    def __init__(self, elements: Sequence[DocumentElement]):
        self.elements = list(elements)
        self.calls: list[str] = []

    async def parse(self, path: str, timeout: float) -> list[DocumentElement]:
        self.calls.append(path)
        return [e.model_copy(deep=True) for e in self.elements]


class FakeVision(BaseVisionModel):
    """Describes every image with the same text."""

    def __init__(self, description: str = "grafik penjualan naik"):
        self.description = description
        self.calls = 0

    def supports(self, element: DocumentElement) -> bool:
        return True

    async def describe_image(self, element: DocumentElement) -> str:
        self.calls += 1
        return self.description


_DEFAULT_FEATURES = (
    ExtractedFeature(brand_name="Toyota", product_name="Avanza", price=230.0, section_ref="S1"),
)


class FakeExtractor(BaseExtractor):
    """Returns ``features`` (default: one Toyota Avanza row), or the result of ``fn(text)``.

    ``fail=True`` raises ``TimeoutError``. Tracks the texts it received and the highest
    number of calls running at the same time (``max_active``).
    """

    def __init__(
        self,
        features: Sequence[ExtractedFeature] = _DEFAULT_FEATURES,
        fn: Callable[[str], Awaitable[list[ExtractedFeature]]] | None = None,
        fail: bool = False,
    ):
        self.features = list(features)
        self.fn = fn
        self.fail = fail
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0

    async def extract(self, text: str) -> list[ExtractedFeature]:
        self.calls.append(text)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.fail:
                raise TimeoutError()
            if self.fn is not None:
                return await self.fn(text)
            return [f.model_copy() for f in self.features]
        finally:
            self.active -= 1


class FakeSTT(BaseSTT):
    """Transcribes every audio to "<n> bytes" (or raises ``error``); records each request."""

    def __init__(self, error: BaseException | None = None):
        self.error = error
        self.requests: list[STTRequest] = []

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def supported_languages(self) -> list[str]:
        return ["*"]

    @property
    def supported_formats(self) -> list[str]:
        return ["webm", "wav", "mp3"]

    async def transcribe(self, audio_bytes: bytes, request: STTRequest) -> STTResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return STTResult(text=f"{len(audio_bytes)} bytes", language=request.language, provider="fake")


class FakeTTS(BaseTTS):
    """Returns the text's bytes as "audio"."""

    @property
    def provider_name(self) -> str:
        return "fake"

    @property
    def supported_voices(self) -> list[str]:
        return ["alloy"]

    @property
    def supported_formats(self) -> list[str]:
        return ["mp3"]

    async def synthesize(self, request: TTSRequest) -> TTSResult:
        return TTSResult(
            audio_bytes=request.text.encode("utf-8"),
            format=request.format.value,
            character_count=len(request.text),
            provider="fake",
        )
