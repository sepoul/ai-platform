"""Config / profile / resolution tests for aiplatform-cli.

All filesystem state is redirected to a tmp dir via AIPLATFORM_CONFIG_DIR
so nothing touches the real `~/.config`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aiplatform_cli import config as cfg


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AIPLATFORM_CONFIG_DIR", str(tmp_path / "cfg"))
    # Clear env that would otherwise win the precedence chain.
    for var in ("AIPLATFORM_API_URL", "AIPLATFORM_TOKEN", "AIPLATFORM_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_login_writes_and_load_reads_back():
    path = cfg.login("https://platform.example/", profile="prod", token="t0ken")
    assert path.exists()

    config = cfg.load_config()
    assert config.current_profile == "prod"
    prof = config.get_profile("prod")
    assert prof.api_url == "https://platform.example"  # trailing slash stripped
    assert prof.token == "t0ken"


def test_load_config_missing_file_returns_empty_default():
    config = cfg.load_config()
    assert config.current_profile == cfg.DEFAULT_PROFILE
    assert config.profiles == {}
    # Reading a profile that doesn't exist yields defaults, never KeyError.
    assert config.get_profile().api_url == cfg.DEFAULT_API_URL


def test_resolve_api_url_precedence(monkeypatch):
    cfg.login("https://from-profile:8000", profile="default")

    # 3. profile
    assert cfg.resolve_api_url() == "https://from-profile:8000"
    # 2. env beats profile
    monkeypatch.setenv("AIPLATFORM_API_URL", "https://from-env:9000/")
    assert cfg.resolve_api_url() == "https://from-env:9000"
    # 1. explicit flag beats env
    assert cfg.resolve_api_url("https://from-flag:7000") == "https://from-flag:7000"


def test_resolve_api_url_default_when_unset():
    assert cfg.resolve_api_url() == cfg.DEFAULT_API_URL


def test_resolve_token_precedence(monkeypatch):
    cfg.login("https://x", profile="default", token="profile-token")
    assert cfg.resolve_token() == "profile-token"
    monkeypatch.setenv("AIPLATFORM_TOKEN", "env-token")
    assert cfg.resolve_token() == "env-token"
    assert cfg.resolve_token("flag-token") == "flag-token"


def test_login_can_target_named_profile_without_switching_current():
    cfg.login("https://a", profile="default")
    cfg.login("https://b", profile="staging", make_current=False)
    config = cfg.load_config()
    assert config.current_profile == "default"
    assert config.get_profile("staging").api_url == "https://b"
    # An explicit --profile still selects it.
    assert cfg.resolve_api_url(profile="staging") == "https://b"
