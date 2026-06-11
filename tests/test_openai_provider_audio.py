"""Tests for the OpenAI provider helpers — `openai_agent`, `transcribe_audio`,
and the media-first-class `AudioInterpreter`.

These live next to `basic_agent` (the Anthropic factory) in
`ai_platform.ai.providers`. The design goal is *backward-compatible and
additive*: the worker base stays engine-free, importing the package never
drags the LLM/ASR stack in, and the transcription path is exercised here with
an **injected fake OpenAI client** so the suite is green without the `[openai]`
extra installed.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from ai_platform.ai.providers.audio import (
    AudioInterpreter,
    TranscriptionResult,
    transcribe_audio,
)
from ai_platform.ai.providers.openai_agent import openai_agent
from ai_platform.jobs.media_service import MediaService
from ai_platform.workspace.storage.blobs.base import PutFilePayload
from ai_platform.workspace.storage.blobs.local import (
    LocalFileRepository,
    LocalFileRepositoryConfig,
)


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeTranscriptions:
    def __init__(self, resp):
        self._resp = resp
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._resp


class _FakeOpenAI:
    """Minimal stand-in for `openai.OpenAI` — only the surface
    `transcribe_audio` touches (`client.audio.transcriptions.create`)."""

    def __init__(self, resp):
        self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions(resp))


@pytest.fixture
def file_repo(tmp_path) -> LocalFileRepository:
    return LocalFileRepository(
        LocalFileRepositoryConfig(root_dir=str(tmp_path), prefix="files")
    )


@pytest.fixture
def media(file_repo: LocalFileRepository) -> MediaService:
    return MediaService(file_repo)


# ---------------------------------------------------------------------------
# transcribe_audio — the thin helper
# ---------------------------------------------------------------------------


def test_transcribe_from_bytes_returns_text():
    fake = _FakeOpenAI(SimpleNamespace(text="hello world"))
    result = transcribe_audio(b"fake-audio-bytes", client=fake, filename="note.m4a")

    assert isinstance(result, TranscriptionResult)
    assert result.text == "hello world"
    assert result.model == "gpt-4o-mini-transcribe"  # default
    # bytes reached the SDK as a (filename, bytes) tuple — the extension is the
    # format hint the API relies on.
    call = fake.audio.transcriptions.calls[0]
    assert call["file"] == ("note.m4a", b"fake-audio-bytes")
    assert call["model"] == "gpt-4o-mini-transcribe"


def test_transcribe_passes_model_language_prompt_and_passthroughs():
    resp = SimpleNamespace(text="bonjour", language="fr", duration=1.5)
    fake = _FakeOpenAI(resp)
    result = transcribe_audio(
        b"x", client=fake, model="whisper-1", language="fr", prompt="mathy terms"
    )

    assert result.text == "bonjour"
    assert result.model == "whisper-1"
    assert result.language == "fr"
    assert result.duration == 1.5
    call = fake.audio.transcriptions.calls[0]
    assert call["model"] == "whisper-1"
    assert call["language"] == "fr"
    assert call["prompt"] == "mathy terms"


def test_transcribe_optional_fields_default_none_when_absent():
    # A bare `text` response (the common `json` format) → no language/duration.
    fake = _FakeOpenAI(SimpleNamespace(text="ok"))
    result = transcribe_audio(b"x", client=fake)
    assert result.language is None
    assert result.duration is None


def test_transcribe_from_path(tmp_path):
    p = tmp_path / "voice.mp3"
    p.write_bytes(b"id3-bytes")
    fake = _FakeOpenAI(SimpleNamespace(text="ok"))

    result = transcribe_audio(str(p), client=fake)

    assert result.text == "ok"
    call = fake.audio.transcriptions.calls[0]
    # path read into bytes; the file's own name becomes the format hint.
    assert call["file"] == ("voice.mp3", b"id3-bytes")


def test_transcribe_rejects_unsupported_input():
    fake = _FakeOpenAI(SimpleNamespace(text=""))
    with pytest.raises(TypeError):
        transcribe_audio(12345, client=fake)  # not bytes / path / file-like


def test_transcribe_without_client_gives_clear_error_when_sdk_absent():
    # The `openai` SDK ships in the worker base, but if it's somehow absent
    # and no client is injected, the helper must fail with a clear, actionable
    # message — not an obscure ModuleNotFoundError. (Skipped when openai *is*
    # importable, since that path can't be exercised then.)
    if importlib.util.find_spec("openai") is not None:
        pytest.skip("openai importable — the missing-SDK path isn't reachable")
    with pytest.raises(ImportError) as ei:
        transcribe_audio(b"abc")
    assert "openai" in str(ei.value).lower()


# ---------------------------------------------------------------------------
# AudioInterpreter — media-first-class over the blob layer
# ---------------------------------------------------------------------------


_AUDIO = b"RIFF\x00\x00\x00\x00WAVEfake-voice-note"


def test_interpreter_transcribes_a_media_ref(media: MediaService):
    ref = media.put(filename="voice.m4a", content_type="audio/m4a", data=_AUDIO)
    fake = _FakeOpenAI(SimpleNamespace(text="the keystone is feature 1"))

    interp = AudioInterpreter(media, client=fake)
    result = interp.transcribe(ref)

    assert result.text == "the keystone is feature 1"
    # The exact bytes that landed in the storage plane reached the SDK, with
    # the original filename (last ref segment) as the format hint.
    name, data = fake.audio.transcriptions.calls[0]["file"]
    assert data == _AUDIO
    assert name == "voice.m4a"


def test_interpreter_accepts_a_bare_storage_ref_string(media: MediaService):
    ref = media.put(filename="clip.wav", content_type="audio/wav", data=_AUDIO)
    fake = _FakeOpenAI(SimpleNamespace(text="t"))

    interp = AudioInterpreter(media, client=fake)
    result = interp.transcribe(ref.storage_ref)  # string, not MediaRef

    assert result.text == "t"


def test_interpreter_per_call_overrides_default_model(media: MediaService):
    ref = media.put(filename="a.m4a", content_type="audio/m4a", data=_AUDIO)
    fake = _FakeOpenAI(SimpleNamespace(text="x"))

    interp = AudioInterpreter(media, model="gpt-4o-mini-transcribe", client=fake)
    interp.transcribe(ref, model="whisper-1")

    assert fake.audio.transcriptions.calls[0]["model"] == "whisper-1"


def test_interpreter_works_over_a_raw_file_repository(file_repo: LocalFileRepository):
    # No MediaService — a bare FileRepository is duck-typed via
    # get_canonical_file_bytes.
    file_repo.put_canonical_file(
        PutFilePayload(
            logical_name="media/abc/clip.wav",
            bytes_data=_AUDIO,
            content_type="audio/wav",
        )
    )
    fake = _FakeOpenAI(SimpleNamespace(text="from-repo"))

    interp = AudioInterpreter(file_repo, client=fake)
    result = interp.transcribe("media/abc/clip.wav")

    assert result.text == "from-repo"
    assert fake.audio.transcriptions.calls[0]["file"] == ("clip.wav", _AUDIO)


def test_interpreter_rejects_an_incompatible_source():
    interp = AudioInterpreter(object())  # neither MediaService nor FileRepository
    with pytest.raises(TypeError):
        interp.transcribe("media/x/y.wav")


# ---------------------------------------------------------------------------
# Package surface — additive, base-importable without the openai SDK
# ---------------------------------------------------------------------------


def test_package_and_modules_import_without_openai_sdk():
    # The whole point of the deferred imports: importing the package and its
    # submodules must succeed even though the `openai` SDK isn't installed in
    # the worker base (it's the `[openai]` extra). This test file's own
    # top-level imports already exercise that; assert the package resolves too.
    import importlib

    pkg = importlib.import_module("ai_platform.ai.providers")
    assert pkg is not None
    for sub in ("basic_agent", "openai_agent", "audio"):
        assert importlib.util.find_spec(f"ai_platform.ai.providers.{sub}") is not None


# ---------------------------------------------------------------------------
# openai_agent — the Anthropic-sibling factory (needs the [openai] extra)
# ---------------------------------------------------------------------------


def test_openai_agent_builds_a_pydantic_ai_agent():
    pytest.importorskip("openai", reason="needs the worker [openai] extra")
    from pydantic_ai import Agent

    agent = openai_agent(model="gpt-4o", instructions="be terse")
    assert isinstance(agent, Agent)
