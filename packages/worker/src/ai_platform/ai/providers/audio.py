"""Audio transcription — media-first-class ASR over the platform's blob layer.

Two entry points, smallest-primitive-first:

- `transcribe_audio(audio, ...)` — the thin helper. Hand it raw bytes, a path,
  or a file-like object and get text back from OpenAI's transcription endpoint
  (Whisper / `gpt-4o-transcribe`). No platform coupling — pure bytes → text.
- `AudioInterpreter` — the media-first-class wrapper. Hand it the same blob
  layer `MediaService` writes to (a `MediaService` *or* a raw `FileRepository`)
  and it transcribes a `storage_ref` straight off the storage plane:
  `media/<uuid>/voice-note.m4a` → text, no manual download dance. This is the
  bridge from PR-1 media ingestion to a transcript.

The `openai` SDK is part of the **worker base** — present in *both* runtimes
(it has no `opentelemetry` dep, so it's safe to share across the otel-split
pools), so transcription works whether the domain is a pydantic_ai-style
(`default`) or crewai-style (`crewai`) one. Imports are still deferred and a
client can be injected (DI / tests), so importing this module never *requires*
the SDK at import time.

Boundary note (platform-requirements.md PR-1 / design §13): transcription is
ASR, which the contract keeps *domain-side*. This ships next to `basic_agent`
as a **provider helper** — a thin factory a domain calls from its own workflow
— not as a platform job or route. The platform still only carries bytes + the
ref; the domain decides when to interpret them.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Optional, Tuple, Union

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import OpenAI

    from ai_platform.jobs.media_service import MediaRef, MediaService
    from ai_platform.session.session import PlatformSession
    from ai_platform.workspace.storage.blobs.base import FileRepository


# An OpenAI "file" upload: either a file-like object or a
# (filename, bytes[, content_type]) tuple. We normalize to the tuple form.
_FileUpload = Union[BinaryIO, Tuple[str, bytes], Tuple[str, bytes, str]]

# Default to the cheap, fast 4o transcription model. Callers wanting
# Whisper or the larger model pass `model=` explicitly.
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"


class TranscriptionResult(BaseModel):
    """What a transcription returns. `text` is always populated; `language`
    and `duration` are passed through only when the model/response format
    surfaces them (e.g. `verbose_json`), so they stay optional."""

    text: str
    model: str
    language: Optional[str] = None
    duration: Optional[float] = None


def _default_client() -> "OpenAI":
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover - only without the worker base dep
        raise ImportError(
            "audio transcription needs the `openai` SDK — it ships in the "
            "worker base (`aiplatform-worker`, both runtimes); install `openai` "
            "in this environment, or inject a client via `client=`."
        ) from e
    return OpenAI()


def _coerce_to_upload(
    audio: Union[bytes, bytearray, str, os.PathLike, BinaryIO],
    filename: str,
) -> _FileUpload:
    """Normalize the many ways a caller can hand us audio into something the
    OpenAI SDK's `file=` accepts. Bytes/paths become a `(name, bytes)` tuple;
    a file-like object is passed straight through."""
    if isinstance(audio, (bytes, bytearray)):
        return (filename, bytes(audio))
    if isinstance(audio, (str, os.PathLike)):
        p = Path(audio)
        return (p.name, p.read_bytes())
    if hasattr(audio, "read"):
        return audio  # file-like; let the SDK stream it
    raise TypeError(
        f"Unsupported audio input {type(audio)!r}: expected bytes, a path, or "
        "a file-like object."
    )


def transcribe_audio(
    audio: Union[bytes, bytearray, str, os.PathLike, BinaryIO],
    *,
    model: str = DEFAULT_TRANSCRIBE_MODEL,
    filename: str = "audio",
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    client: Optional["OpenAI"] = None,
) -> TranscriptionResult:
    """Transcribe audio to text via OpenAI's transcription endpoint.

    `audio` may be raw bytes, a filesystem path, or a file-like object.
    `filename` only matters for bytes input (the SDK uses the extension as a
    format hint, e.g. `voice.m4a`). Pass a `client` to inject your own
    configured `OpenAI()` (or a fake, in tests); otherwise one is constructed
    lazily, which requires the `[openai]` extra.
    """
    upload = _coerce_to_upload(audio, filename)
    client = client or _default_client()

    kwargs: dict = {"model": model, "file": upload}
    if language:
        kwargs["language"] = language
    if prompt:
        kwargs["prompt"] = prompt

    resp = client.audio.transcriptions.create(**kwargs)

    return TranscriptionResult(
        text=getattr(resp, "text", "") or "",
        model=model,
        language=getattr(resp, "language", None),
        duration=getattr(resp, "duration", None),
    )


class AudioInterpreter:
    """Media-first-class transcription: a `storage_ref` in, a transcript out.

    A domain that ingested a voice note via `POST /media` can turn the
    resulting ref into text without re-implementing the download. Accepts any
    media source, duck-typed so this module imports without a hard dependency
    on any of them:

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
        model: str = DEFAULT_TRANSCRIBE_MODEL,
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

    def transcribe(
        self,
        ref: "Union[str, MediaRef]",
        *,
        model: Optional[str] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> TranscriptionResult:
        """Download the blob behind `ref` and transcribe it. `ref` may be a
        bare `storage_ref` string or a `MediaRef` (as returned by
        `MediaService.put` / `POST /media`)."""
        storage_ref = getattr(ref, "storage_ref", ref)
        data = self._read_bytes(storage_ref)
        filename = storage_ref.rsplit("/", 1)[-1] or "audio"
        return transcribe_audio(
            data,
            model=model or self.model,
            filename=filename,
            language=language,
            prompt=prompt,
            client=self._client,
        )
