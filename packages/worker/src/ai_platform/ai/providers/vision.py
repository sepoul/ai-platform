"""Image description — media-first-class vision over the platform's blob layer.

Two entry points, smallest-primitive-first:

- `describe_image(image, ...)` — the thin helper. Hand it raw bytes, a path,
  or a file-like object and get text back from OpenAI's vision-capable chat
  endpoint (`gpt-4o-mini` & friends). No platform coupling — pure bytes → text:
  the image is base64-encoded into a `data:` URI and sent as an `image_url`
  content part alongside an optional instruction `prompt`.
- `ImageInterpreter` — the media-first-class wrapper. Hand it the same blob
  layer `MediaService` writes to (a `MediaService` *or* a raw `FileRepository`)
  and it describes a `storage_ref` straight off the storage plane:
  `media/<uuid>/diagram.png` → text, no manual download dance. This is the
  bridge from PR-1 media ingestion to a description.

The `openai` SDK is part of the **worker base** — present in *both* runtimes
(it has no `opentelemetry` dep, so it's safe to share across the otel-split
pools), so description works whether the domain is a pydantic_ai-style
(`default`) or crewai-style (`crewai`) one. Imports are still deferred and a
client can be injected (DI / tests), so importing this module never *requires*
the SDK at import time.

Boundary note (platform-requirements.md PR-1 / design §13): describing an image
is interpretation, which the contract keeps *domain-side*. This ships next to
`basic_agent` as a **provider helper** — a thin factory a domain calls from its
own workflow — not as a platform job or route. Text in, text out only: no
math / LaTeX / concept-specific parsing lives here; structured parsing is the
domain's job. The platform still only carries bytes + the ref; the domain
decides when to interpret them.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Optional, Union

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import OpenAI

    from ai_platform.jobs.media_service import MediaRef, MediaService
    from ai_platform.session.session import PlatformSession
    from ai_platform.workspace.storage.blobs.base import FileRepository


# Default to the cheap, fast, vision-capable 4o model — the visual sibling of
# the 4o choice in audio. Callers wanting a larger model pass `model=`.
DEFAULT_VISION_MODEL = "gpt-4o-mini"

# The generic instruction used when a caller doesn't supply their own `prompt`.
DEFAULT_VISION_PROMPT = "Describe the contents of this image."

# Magic-byte → MIME map for the data URI. Vision wants a sensible media type in
# the `data:` URL; we sniff the common formats and fall back to PNG.
_MIME_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


class ImageDescriptionResult(BaseModel):
    """What a description returns. `text` is the model's prose; `model` records
    which vision model produced it."""

    text: str
    model: str


def _default_client() -> "OpenAI":
    try:
        from openai import OpenAI
    except ImportError as e:  # pragma: no cover - only without the worker base dep
        raise ImportError(
            "image description needs the `openai` SDK — it ships in the "
            "worker base (`aiplatform-worker`, both runtimes); install `openai` "
            "in this environment, or inject a client via `client=`."
        ) from e
    return OpenAI()


def _sniff_mime(data: bytes) -> str:
    """Best-effort MIME from the leading bytes. WebP needs the `RIFF....WEBP`
    container check; everything else is a simple prefix. Defaults to PNG."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for sig, mime in _MIME_SIGNATURES:
        if data.startswith(sig):
            return mime
    return "image/png"


def _coerce_to_data_uri(
    image: Union[bytes, bytearray, str, os.PathLike, BinaryIO],
) -> str:
    """Normalize the many ways a caller can hand us an image into the
    `data:<mime>;base64,<...>` URI OpenAI's `image_url` content part accepts.
    Bytes/paths/file-likes are all read into bytes, sniffed for a MIME type,
    and base64-encoded."""
    if isinstance(image, (bytes, bytearray)):
        data = bytes(image)
    elif isinstance(image, (str, os.PathLike)):
        data = Path(image).read_bytes()
    elif hasattr(image, "read"):
        data = image.read()  # file-like; pull the bytes out
    else:
        raise TypeError(
            f"Unsupported image input {type(image)!r}: expected bytes, a path, "
            "or a file-like object."
        )
    mime = _sniff_mime(data)
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _extract_text(resp: object) -> str:
    """Pull the assistant text out of a chat-completions response, defensively
    (mirrors the getattr style in `transcribe_audio`)."""
    choices = getattr(resp, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return getattr(message, "content", "") or ""


def describe_image(
    image: Union[bytes, bytearray, str, os.PathLike, BinaryIO],
    *,
    prompt: Optional[str] = None,
    model: str = DEFAULT_VISION_MODEL,
    client: Optional["OpenAI"] = None,
) -> ImageDescriptionResult:
    """Describe an image as text via OpenAI's vision-capable chat endpoint.

    `image` may be raw bytes, a filesystem path, or a file-like object; it is
    base64-encoded into a `data:` URI and sent as an `image_url` content part.
    `prompt` is the instruction the model follows (default: a generic
    "Describe the contents of this image."). Pass a `client` to inject your own
    configured `OpenAI()` (or a fake, in tests); otherwise one is constructed
    lazily, which requires the `[openai]` extra.
    """
    data_uri = _coerce_to_data_uri(image)
    client = client or _default_client()

    instruction = prompt or DEFAULT_VISION_PROMPT
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    )

    return ImageDescriptionResult(text=_extract_text(resp), model=model)


class ImageInterpreter:
    """Media-first-class description: a `storage_ref` in, a description out.

    A domain that ingested an image via `POST /media` can turn the resulting
    ref into text without re-implementing the download. Accepts any media
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
        model: str = DEFAULT_VISION_MODEL,
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

    def interpret(
        self,
        image_ref: "Union[str, MediaRef]",
        *,
        prompt: Optional[str] = None,
        model: Optional[str] = None,
    ) -> ImageDescriptionResult:
        """Download the blob behind `image_ref` and describe it. `image_ref`
        may be a bare `storage_ref` string or a `MediaRef` (as returned by
        `MediaService.put` / `POST /media`)."""
        storage_ref = getattr(image_ref, "storage_ref", image_ref)
        data = self._read_bytes(storage_ref)
        return describe_image(
            data,
            prompt=prompt,
            model=model or self.model,
            client=self._client,
        )
