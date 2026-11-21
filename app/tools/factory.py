"""The only place that picks concrete tool implementations (DESIGN_GROUP_E.md §3.2).

Called by the composition root at startup. Services, engines and routers depend on the
``Base…`` contracts in ``app/tools/<tool>/base.py`` and receive their tools through the
constructor; they never call this module.

To switch a tool: add an implementation next to its ``base.py``, add a branch here, and
change the provider constant in ``app/core/config.py``.
"""
from __future__ import annotations

from app.core.config import PROJECT_ROOT, app_config, secrets
from app.tools.document_parser.base import BaseDocumentParser
from app.tools.document_parser.docling_process import DoclingProcess
from app.tools.embedding.base import BaseEmbedder
from app.tools.embedding.openai_embedder import OpenAIEmbedder
from app.tools.llm.base import BaseLLM
from app.tools.llm.openai_llm import OpenAILLM
from app.tools.vector_store.base import BaseVectorStore
from app.tools.vector_store.chroma import ChromaVectorStore
from app.tools.vision.base import BaseVisionModel
from app.tools.vision.openai_vision import OpenAIVision

# profile → (model, timeout seconds, retries, purpose in llm_calls). DESIGN_GROUP_B.md §5, C §7.3.
_OPENAI_LLM_PROFILES = {
    "llm": (app_config.OPENAI_LLM_MODEL, app_config.LLM_TIMEOUT_CHAT, 1, "synthesizer"),
    "chat": (app_config.OPENAI_CHAT_MODEL, app_config.LLM_TIMEOUT_CHAT, 1, "synthesizer"),
    "router": (app_config.OPENAI_ROUTER_MODEL, app_config.LLM_TIMEOUT_ROUTER, 1, "router"),
    "title": (app_config.OPENAI_TITLE_MODEL, app_config.LLM_TIMEOUT_TITLE, 0, "title"),
    "nl2sql": (app_config.OPENAI_EXTRACTION_MODEL, app_config.LLM_TIMEOUT_NL2SQL, 1, "nl2sql"),
}


def _unknown(tool: str, provider: str) -> ValueError:
    return ValueError(f"Unknown {tool} provider: '{provider}'")


def build_llm(profile: str = "llm", temperature: float = 0.0) -> BaseLLM:
    """An LLM for one use (``chat``, ``router``, ``title``, ``nl2sql``, ``llm``)."""
    provider = app_config.LLM_PROVIDER.lower()
    if provider == "openai":
        if profile not in _OPENAI_LLM_PROFILES:
            raise ValueError(f"Unknown LLM profile: '{profile}'")
        model, timeout, retries, purpose = _OPENAI_LLM_PROFILES[profile]
        return OpenAILLM(
            api_key=secrets.OPENAI_API_KEY,
            model=model,
            temperature=temperature,
            timeout=timeout,
            max_retries=retries,
            purpose=purpose,
        )
    raise _unknown("LLM", provider)


def build_embedder() -> BaseEmbedder:
    provider = app_config.EMBEDDING_PROVIDER.lower()
    if provider == "openai":
        return OpenAIEmbedder(
            api_key=secrets.OPENAI_API_KEY,
            model=app_config.OPENAI_EMBEDDING_MODEL,
            batch_size=app_config.EMBED_BATCH_SIZE,
            timeout=app_config.EMBED_TIMEOUT,
        )
    raise _unknown("embedding", provider)


def build_vector_store(embedder: BaseEmbedder) -> BaseVectorStore:
    provider = app_config.VECTOR_STORE_PROVIDER.lower()
    if provider == "chroma":
        return ChromaVectorStore(embedder)
    raise _unknown("vector store", provider)


def build_document_parser() -> BaseDocumentParser:
    provider = app_config.DOCUMENT_PARSER_PROVIDER.lower()
    if provider == "docling":
        return DoclingProcess()
    raise _unknown("document parser", provider)


_VISION_PROMPT = PROJECT_ROOT / "prompts" / "vision_description.md"
_VISION_FALLBACK_PROMPT = "You are an expert data analyst. Describe this chart or image in detail."


def build_vision() -> BaseVisionModel:
    provider = app_config.VISION_PROVIDER.lower()
    if provider == "openai":
        try:
            prompt = _VISION_PROMPT.read_text(encoding="utf-8")
        except FileNotFoundError:
            prompt = _VISION_FALLBACK_PROMPT
        return OpenAIVision(prompt_template=prompt)
    raise _unknown("vision", provider)
