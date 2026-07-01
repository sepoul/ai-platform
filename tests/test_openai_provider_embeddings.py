"""Tests for the OpenAI embedding helpers — `embed_text` and the
media-first-class `EmbeddingsInterpreter`.

These live next to `audio` (the ASR helpers), `vision` (the vision helpers),
and `basic_agent` (the Anthropic factory) in `ai_platform.ai.providers`. The
design goal is *backward-compatible and additive*: the worker base stays
engine-free, importing the package never drags the LLM/embedding stack in, and
the embedding path is exercised here with an **injected fake OpenAI client** so
the suite is green without the `[openai]` extra installed.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from ai_platform.ai.providers.embeddings import (
    EmbeddingResult,
    EmbeddingsInterpreter,
    embed_text,
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


_VECTOR = [0.1, -0.2, 0.3, 0.4]
_USAGE = SimpleNamespace(prompt_tokens=7, total_tokens=7)


def _embeddings_response(vector, usage=_USAGE) -> SimpleNamespace:
    """Shape an embeddings response down to what `embed_text` reads:
    `resp.data[0].embedding` and `resp.usage`."""
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=vector)],
        usage=usage,
    )


class _FakeEmbeddings:
    def __init__(self, resp):
        self._resp = resp
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._resp


class _FakeOpenAI:
    """Minimal stand-in for `openai.OpenAI` — only the surface `embed_text`
    touches (`client.embeddings.create`)."""

    def __init__(self, resp):
        self.embeddings = _FakeEmbeddings(resp)


@pytest.fixture
def file_repo(tmp_path) -> LocalFileRepository:
    return LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )


@pytest.fixture
def media(file_repo: LocalFileRepository) -> MediaService:
    return MediaService(file_repo)


# ---------------------------------------------------------------------------
# embed_text — the thin helper
# ---------------------------------------------------------------------------


def test_embed_from_text_returns_vector():
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))
    result = embed_text("the keystone is feature 1", client=fake)

    assert isinstance(result, EmbeddingResult)
    assert result.vector == _VECTOR
    assert result.model == "text-embedding-3-small"  # default
    assert result.usage is _USAGE
    # The text reached the SDK as the `input` kwarg with the default model.
    call = fake.embeddings.calls[0]
    assert call["input"] == "the keystone is feature 1"
    assert call["model"] == "text-embedding-3-small"


def test_embed_passes_model_through():
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))
    result = embed_text("x", client=fake, model="text-embedding-3-large")

    assert result.model == "text-embedding-3-large"
    assert fake.embeddings.calls[0]["model"] == "text-embedding-3-large"


def test_embed_usage_defaults_none_when_absent():
    fake = _FakeOpenAI(_embeddings_response(_VECTOR, usage=None))
    result = embed_text("x", client=fake)
    assert result.usage is None


def test_embed_without_client_gives_clear_error_when_sdk_absent():
    # The `openai` SDK ships in the worker base, but if it's somehow absent and
    # no client is injected, the helper must fail with a clear, actionable
    # message — not an obscure ModuleNotFoundError. (Skipped when openai *is*
    # importable, since that path can't be exercised then.)
    if importlib.util.find_spec("openai") is not None:
        pytest.skip("openai importable — the missing-SDK path isn't reachable")
    with pytest.raises(ImportError) as ei:
        embed_text("x")
    assert "openai" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# EmbeddingsInterpreter — media-first-class over the blob layer
# ---------------------------------------------------------------------------


_TEXT = "a chunk of book text to embed"
_TEXT_BYTES = _TEXT.encode("utf-8")


def test_interpreter_embeds_in_memory_text():
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))

    interp = EmbeddingsInterpreter(object(), client=fake)  # media unused for embed()
    result = interp.embed(_TEXT)

    assert result.vector == _VECTOR
    assert fake.embeddings.calls[0]["input"] == _TEXT


def test_interpreter_embeds_a_media_ref(media: MediaService):
    ref = media.put(filename="chunk.txt", content_type="text/plain", data=_TEXT_BYTES)
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))

    interp = EmbeddingsInterpreter(media, client=fake)
    result = interp.embed_ref(ref)

    assert result.vector == _VECTOR
    # The exact bytes that landed in the storage plane were decoded to utf-8
    # text and reached the SDK as `input`.
    assert fake.embeddings.calls[0]["input"] == _TEXT


def test_interpreter_accepts_a_bare_storage_ref_string(media: MediaService):
    ref = media.put(filename="c.txt", content_type="text/plain", data=_TEXT_BYTES)
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))

    interp = EmbeddingsInterpreter(media, client=fake)
    result = interp.embed_ref(ref.storage_ref)  # string, not MediaRef

    assert result.vector == _VECTOR


def test_interpreter_per_call_overrides_default_model(media: MediaService):
    ref = media.put(filename="c.txt", content_type="text/plain", data=_TEXT_BYTES)
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))

    interp = EmbeddingsInterpreter(
        media, model="text-embedding-3-small", client=fake
    )
    interp.embed_ref(ref, model="text-embedding-3-large")

    assert fake.embeddings.calls[0]["model"] == "text-embedding-3-large"


def test_interpreter_works_over_a_raw_file_repository(file_repo: LocalFileRepository):
    # No MediaService — a bare FileRepository is duck-typed via
    # get_canonical_file_bytes.
    file_repo.put_canonical_file(
        PutFilePayload(
            logical_name="media/abc/chunk.txt",
            bytes_data=_TEXT_BYTES,
            content_type="text/plain",
        )
    )
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))

    interp = EmbeddingsInterpreter(file_repo, client=fake)
    result = interp.embed_ref("media/abc/chunk.txt")

    assert result.vector == _VECTOR
    assert fake.embeddings.calls[0]["input"] == _TEXT


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

    sess = _FakeSession(_TEXT_BYTES)
    fake = _FakeOpenAI(_embeddings_response(_VECTOR))

    interp = EmbeddingsInterpreter(sess, client=fake)
    result = interp.embed_ref("media/abc/chunk.txt")

    assert result.vector == _VECTOR
    assert sess.refs == ["media/abc/chunk.txt"]
    assert fake.embeddings.calls[0]["input"] == _TEXT


def test_interpreter_rejects_an_incompatible_source():
    interp = EmbeddingsInterpreter(object())  # not a session / MediaService / repo
    with pytest.raises(TypeError):
        interp.embed_ref("media/x/y.txt")


# ---------------------------------------------------------------------------
# Package surface — additive, base-importable without the openai SDK
# ---------------------------------------------------------------------------


def test_embeddings_module_imports_without_openai_sdk():
    # The whole point of the deferred imports: importing the module must
    # succeed even without the `openai` SDK (it's the `[openai]` extra). This
    # file's own top-level imports already exercise that; assert it resolves.
    assert (
        importlib.util.find_spec("ai_platform.ai.providers.embeddings")
        is not None
    )
