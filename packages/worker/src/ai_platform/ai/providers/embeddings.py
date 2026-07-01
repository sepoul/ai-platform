"""Text embeddings — media-first-class vectors over the platform's blob layer.

Two entry points, smallest-primitive-first:

- `embed_text(text, ...)` — the thin helper. Hand it a string and get an
  embedding vector back from OpenAI's embeddings endpoint
  (`text-embedding-3-small` & friends). No platform coupling — pure text →
  vector.
- `EmbeddingsInterpreter` — the media-first-class wrapper. Hand it the same
  blob layer `MediaService` writes to (a `PlatformSession`, a `MediaService`,
  *or* a raw `FileRepository`) and it embeds the text behind a `storage_ref`
  straight off the storage plane: `media/<uuid>/chunk.txt` → vector, no manual
  download dance. This is the bridge from PR-1 media ingestion to a vector.

The `openai` SDK is part of the **worker base** — present in *both* runtimes
(it has no `opentelemetry` dep, so it's safe to share across the otel-split
pools), so embedding works whether the domain is a pydantic_ai-style
(`default`) or crewai-style (`crewai`) one. Imports are still deferred and a
client can be injected (DI / tests), so importing this module never *requires*
the SDK at import time.

Boundary note (platform-requirements.md PR-1 / design §13): producing an
embedding is interpretation, which the contract keeps *domain-side*. This ships
next to `basic_agent` as a **provider helper** — a thin factory a domain calls
from its own workflow — not as a platform job or route. Text in, vector out
only: no chunking, no similarity search, and *no* vector store lives here —
pgvector / retrieval are domain-owned. The platform still only carries bytes +
the ref; the domain decides when to interpret them.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Union

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import OpenAI

    from ai_platform.jobs.media_service import MediaRef, MediaService
    from ai_platform.session.session import PlatformSession
    from ai_platform.workspace.storage.blobs.base import FileRepository


# Default to the cheap, fast small embedding model — the embedding sibling of
# the 4o-mini choices in audio/vision. Callers wanting the larger model
# (`text-embedding-3-large`) pass `model=` explicitly.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class EmbeddingResult(BaseModel):
    """What an embedding returns. `vector` is the dense float embedding;
    `model` records which embedding model produced it; `usage` passes through
    the SDK's token-usage object (whatever shape it has) when present, so
    callers can account cost without this helper interpreting it."""

    vector: List[float]
    model: str
    usage: Optional[Any] = None


def _default_client() -> "OpenAI":
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover - only without the worker base dep
        raise ImportError(
            "text embedding needs the `openai` SDK — it ships in the "
            "worker base (`aiplatform-worker`, both runtimes); install `openai` "
            "in this environment, or inject a client via `client=`."
        ) from e
    return OpenAI()


def _extract_vector(resp: object) -> List[float]:
    """Pull the embedding vector out of an embeddings response, defensively
    (mirrors the getattr style in `transcribe_audio` / `describe_image`).
    Shape: `resp.data[0].embedding`."""
    data = getattr(resp, "data", None) or []
    if not data:
        return []
    embedding = getattr(data[0], "embedding", None)
    return list(embedding) if embedding is not None else []


def embed_text(
    text: str,
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
    client: Optional["OpenAI"] = None,
) -> EmbeddingResult:
    """Embed a string as a dense vector via OpenAI's embeddings endpoint.

    `text` is the input to embed. Pass a `client` to inject your own configured
    `OpenAI()` (or a fake, in tests); otherwise one is constructed lazily, which
    requires the `[openai]` extra. `usage` is passed through untouched from the
    SDK response so the caller can account tokens.
    """
    client = client or _default_client()

    resp = client.embeddings.create(model=model, input=text)

    return EmbeddingResult(
        vector=_extract_vector(resp),
        model=model,
        usage=getattr(resp, "usage", None),
    )


class EmbeddingsInterpreter:
    """Media-first-class embedding: a `storage_ref` in, a vector out.

    A domain that ingested a text blob via `POST /media` can turn the resulting
    ref into a vector without re-implementing the download. Accepts any media
    source, duck-typed so this module imports without a hard dependency on any
    of them:

    - a `PlatformSession` (**preferred** — the public, typed client; what an
      execution node should use to read a blob off the storage plane rather
      than reaching into the backend),
    - a `MediaService` (in-process, prefix-scoped), or
    - a raw `FileRepository` (in-process, lowest level).
    """

    def __init__(
        self,
        media: "Union[PlatformSession, MediaService, FileRepository]",
        *,
        model: str = DEFAULT_EMBEDDING_MODEL,
        client: "Optional[OpenAI]" = None,
    ):
        self.media = media
        self.model = model
        self._client = client

    def _read_bytes(self, storage_ref: str) -> bytes:
        src = self.media
        # PlatformSession.download_media(ref) -> bytes. The public-client path,
        # preferred for domain execution (no reach into the storage backend).
        if hasattr(src, "download_media"):
            return src.download_media(storage_ref)
        # MediaService.download(ref) -> (bytes, content_type); inherits the
        # `media/` prefix scoping.
        if hasattr(src, "download"):
            data, _ct = src.download(storage_ref)
            return data
        # Raw FileRepository fallback.
        if hasattr(src, "get_canonical_file_bytes"):
            return src.get_canonical_file_bytes(storage_ref)
        raise TypeError(
            f"{type(src)!r} is not a PlatformSession, MediaService, or "
            "FileRepository: expected a `.download_media`, `.download`, or "
            "`.get_canonical_file_bytes` method."
        )

    def embed(
        self,
        text: str,
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResult:
        """Embed a string directly (no download) — the in-memory counterpart to
        `embed_ref`, for text a domain already holds."""
        return embed_text(
            text,
            model=model or self.model,
            client=self._client,
        )

    def embed_ref(
        self,
        ref: "Union[str, MediaRef]",
        *,
        model: Optional[str] = None,
    ) -> EmbeddingResult:
        """Download the blob behind `ref`, decode it as UTF-8 text, and embed
        it. `ref` may be a bare `storage_ref` string or a `MediaRef` (as
        returned by `MediaService.put` / `POST /media`)."""
        storage_ref = getattr(ref, "storage_ref", ref)
        data = self._read_bytes(storage_ref)
        text = data.decode("utf-8")
        return self.embed(text, model=model)
