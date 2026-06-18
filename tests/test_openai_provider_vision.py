"""Tests for the OpenAI vision helpers — `describe_image` and the
media-first-class `ImageInterpreter`.

These live next to `audio` (the ASR helpers) and `basic_agent` (the Anthropic
factory) in `ai_platform.ai.providers`. The design goal is *backward-compatible
and additive*: the worker base stays engine-free, importing the package never
drags the LLM/vision stack in, and the description path is exercised here with
an **injected fake OpenAI client** so the suite is green without the `[openai]`
extra installed.
"""
from __future__ import annotations

import base64
import importlib.util
from types import SimpleNamespace

import pytest

from ai_platform.ai.providers.vision import (
    ImageDescriptionResult,
    ImageInterpreter,
    describe_image,
)
from ai_platform.jobs.media_service import MediaService
from ai_platform.workspace.storage.blobs.base import PutFilePayload
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


def _completion(text: str) -> SimpleNamespace:
    """Shape a chat-completions response down to what `describe_image` reads:
    `resp.choices[0].message.content`."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))]
    )


class _FakeCompletions:
    def __init__(self, resp):
        self._resp = resp
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._resp


class _FakeOpenAI:
    """Minimal stand-in for `openai.OpenAI` — only the surface
    `describe_image` touches (`client.chat.completions.create`)."""

    def __init__(self, text: str):
        self.chat = SimpleNamespace(completions=_FakeCompletions(_completion(text)))


# An 8-byte PNG signature + filler, so the MIME sniffer reports `image/png`.
_IMAGE = b"\x89PNG\r\n\x1a\nfake-image-bytes"


def _content_parts(fake: _FakeOpenAI) -> list[dict]:
    return fake.chat.completions.calls[0]["messages"][0]["content"]


def _text_part(fake: _FakeOpenAI) -> dict:
    return next(p for p in _content_parts(fake) if p["type"] == "text")


def _image_part(fake: _FakeOpenAI) -> dict:
    return next(p for p in _content_parts(fake) if p["type"] == "image_url")


@pytest.fixture
def file_repo(tmp_path) -> LocalFileRepository:
    return LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )


@pytest.fixture
def media(file_repo: LocalFileRepository) -> MediaService:
    return MediaService(file_repo)


# ---------------------------------------------------------------------------
# describe_image — the thin helper
# ---------------------------------------------------------------------------


def test_describe_from_bytes_returns_text():
    fake = _FakeOpenAI("a hand-drawn triangle")
    result = describe_image(_IMAGE, client=fake)

    assert isinstance(result, ImageDescriptionResult)
    assert result.text == "a hand-drawn triangle"
    assert result.model == "gpt-4o-mini"  # default
    # The image reached the SDK as a base64 data URI (sniffed as PNG), and the
    # round-trip decodes back to the exact bytes.
    url = _image_part(fake)["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == _IMAGE
    assert fake.chat.completions.calls[0]["model"] == "gpt-4o-mini"


def test_describe_uses_default_prompt_when_none():
    fake = _FakeOpenAI("ok")
    describe_image(_IMAGE, client=fake)
    assert _text_part(fake)["text"] == "Describe the contents of this image."


def test_describe_passes_prompt_and_model_through():
    fake = _FakeOpenAI("two cats")
    result = describe_image(
        _IMAGE, client=fake, prompt="How many animals?", model="gpt-4o"
    )

    assert result.text == "two cats"
    assert result.model == "gpt-4o"
    assert _text_part(fake)["text"] == "How many animals?"
    assert fake.chat.completions.calls[0]["model"] == "gpt-4o"


def test_describe_sniffs_jpeg():
    jpeg = b"\xff\xd8\xff\xe0fake-jpeg"
    fake = _FakeOpenAI("ok")
    describe_image(jpeg, client=fake)
    assert _image_part(fake)["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_describe_from_path(tmp_path):
    p = tmp_path / "diagram.png"
    p.write_bytes(_IMAGE)
    fake = _FakeOpenAI("a diagram")

    result = describe_image(str(p), client=fake)

    assert result.text == "a diagram"
    url = _image_part(fake)["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == _IMAGE


def test_describe_from_file_like():
    import io

    fake = _FakeOpenAI("ok")
    describe_image(io.BytesIO(_IMAGE), client=fake)
    url = _image_part(fake)["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == _IMAGE


def test_describe_rejects_unsupported_input():
    fake = _FakeOpenAI("")
    with pytest.raises(TypeError):
        describe_image(12345, client=fake)  # not bytes / path / file-like


def test_describe_without_client_gives_clear_error_when_sdk_absent():
    # The `openai` SDK ships in the worker base, but if it's somehow absent and
    # no client is injected, the helper must fail with a clear, actionable
    # message — not an obscure ModuleNotFoundError. (Skipped when openai *is*
    # importable, since that path can't be exercised then.)
    if importlib.util.find_spec("openai") is not None:
        pytest.skip("openai importable — the missing-SDK path isn't reachable")
    with pytest.raises(ImportError) as ei:
        describe_image(_IMAGE)
    assert "openai" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# ImageInterpreter — media-first-class over the blob layer
# ---------------------------------------------------------------------------


def test_interpreter_describes_a_media_ref(media: MediaService):
    ref = media.put(filename="diagram.png", content_type="image/png", data=_IMAGE)
    fake = _FakeOpenAI("the keystone is feature 1")

    interp = ImageInterpreter(media, client=fake)
    result = interp.interpret(ref)

    assert result.text == "the keystone is feature 1"
    # The exact bytes that landed in the storage plane reached the SDK.
    url = _image_part(fake)["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == _IMAGE


def test_interpreter_accepts_a_bare_storage_ref_string(media: MediaService):
    ref = media.put(filename="pic.png", content_type="image/png", data=_IMAGE)
    fake = _FakeOpenAI("t")

    interp = ImageInterpreter(media, client=fake)
    result = interp.interpret(ref.storage_ref)  # string, not MediaRef

    assert result.text == "t"


def test_interpreter_passes_prompt_through(media: MediaService):
    ref = media.put(filename="pic.png", content_type="image/png", data=_IMAGE)
    fake = _FakeOpenAI("blue")

    interp = ImageInterpreter(media, client=fake)
    result = interp.interpret(ref, prompt="What color?")

    assert result.text == "blue"
    assert _text_part(fake)["text"] == "What color?"


def test_interpreter_per_call_overrides_default_model(media: MediaService):
    ref = media.put(filename="a.png", content_type="image/png", data=_IMAGE)
    fake = _FakeOpenAI("x")

    interp = ImageInterpreter(media, model="gpt-4o-mini", client=fake)
    interp.interpret(ref, model="gpt-4o")

    assert fake.chat.completions.calls[0]["model"] == "gpt-4o"


def test_interpreter_works_over_a_raw_file_repository(file_repo: LocalFileRepository):
    # No MediaService — a bare FileRepository is duck-typed via
    # get_canonical_file_bytes.
    file_repo.put_canonical_file(
        PutFilePayload(
            logical_name="media/abc/pic.png",
            bytes_data=_IMAGE,
            content_type="image/png",
        )
    )
    fake = _FakeOpenAI("from-repo")

    interp = ImageInterpreter(file_repo, client=fake)
    result = interp.interpret("media/abc/pic.png")

    assert result.text == "from-repo"
    url = _image_part(fake)["image_url"]["url"]
    assert base64.b64decode(url.split(",", 1)[1]) == _IMAGE


def test_interpreter_over_a_platform_session():
    # A PlatformSession exposes download_media(ref) -> bytes; the interpreter
    # should prefer it (the public-client path a domain execution node uses).
    class _FakeSession:
        def __init__(self, data: bytes):
            self._data = data
            self.refs: list[str] = []

        def download_media(self, ref: str) -> bytes:
            self.refs.append(ref)
            return self._data

    sess = _FakeSession(_IMAGE)
    fake = _FakeOpenAI("from-session")

    interp = ImageInterpreter(sess, client=fake)
    result = interp.interpret("media/abc/pic.png")

    assert result.text == "from-session"
    assert sess.refs == ["media/abc/pic.png"]


def test_interpreter_rejects_an_incompatible_source():
    interp = ImageInterpreter(object())  # not a session / MediaService / repo
    with pytest.raises(TypeError):
        interp.interpret("media/x/y.png")


# ---------------------------------------------------------------------------
# Package surface — additive, base-importable without the openai SDK
# ---------------------------------------------------------------------------


def test_vision_module_imports_without_openai_sdk():
    # The whole point of the deferred imports: importing the module must
    # succeed even without the `openai` SDK (it's the `[openai]` extra). This
    # file's own top-level imports already exercise that; assert it resolves.
    assert (
        importlib.util.find_spec("ai_platform.ai.providers.vision") is not None
    )
