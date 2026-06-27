"""Config + profile management — the `aiplatform login` home.

Stores named profiles (each a base API URL + optional auth token) in a
JSON file, `az login`-style. Today auth is a no-op on the platform, but
the profile gives it a natural home for the day a token lands.

Resolution precedence (highest first) for both API URL and token:

  1. an explicit CLI flag (`--api-url` / `--token`)
  2. an environment variable (`AIPLATFORM_API_URL` / `AIPLATFORM_TOKEN`)
  3. the selected profile in the config file
  4. (api-url only) the built-in default

Config location: ``$AIPLATFORM_CONFIG_DIR/config.json`` if set, else
``~/.config/aiplatform/config.json``. JSON (not TOML) so writing needs no
third-party dependency — this module is stdlib-only.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_API_URL = "http://127.0.0.1:8000"
DEFAULT_PROFILE = "default"

_ENV_CONFIG_DIR = "AIPLATFORM_CONFIG_DIR"
_ENV_API_URL = "AIPLATFORM_API_URL"
_ENV_TOKEN = "AIPLATFORM_TOKEN"
_ENV_PROFILE = "AIPLATFORM_PROFILE"


def config_path() -> Path:
    """Absolute path to the config file (may not exist yet)."""
    base = os.environ.get(_ENV_CONFIG_DIR)
    root = Path(base) if base else Path.home() / ".config" / "aiplatform"
    return root / "config.json"


@dataclass
class Profile:
    api_url: str = DEFAULT_API_URL
    token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"api_url": self.api_url}
        if self.token is not None:
            out["token"] = self.token
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Profile":
        return cls(
            api_url=raw.get("api_url", DEFAULT_API_URL),
            token=raw.get("token"),
        )


@dataclass
class Config:
    current_profile: str = DEFAULT_PROFILE
    profiles: dict[str, Profile] = field(default_factory=dict)

    def get_profile(self, name: str | None = None) -> Profile:
        """Return the named profile (or the current one). Missing → a
        fresh default Profile, so first-run reads never KeyError."""
        key = name or self.current_profile
        return self.profiles.get(key, Profile())

    def set_profile(self, name: str, profile: Profile) -> None:
        self.profiles[name] = profile

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_profile": self.current_profile,
            "profiles": {k: v.to_dict() for k, v in self.profiles.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Config":
        return cls(
            current_profile=raw.get("current_profile", DEFAULT_PROFILE),
            profiles={
                k: Profile.from_dict(v) for k, v in (raw.get("profiles") or {}).items()
            },
        )


def load_config() -> Config:
    """Read the config file, or an empty Config if none exists / is unreadable."""
    path = config_path()
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return Config()
    return Config.from_dict(raw)


def save_config(config: Config) -> Path:
    """Persist the config, creating the directory. Returns the path written."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), indent=2) + "\n", encoding="utf-8")
    # Token is mildly sensitive; keep the file owner-only when possible.
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover — non-POSIX / restricted FS
        pass
    return path


def login(api_url: str, *, profile: str = DEFAULT_PROFILE, token: str | None = None,
          make_current: bool = True) -> Path:
    """Create/update a profile and persist it. Returns the config path."""
    config = load_config()
    config.set_profile(profile, Profile(api_url=api_url.rstrip("/"), token=token))
    if make_current:
        config.current_profile = profile
    return save_config(config)


def resolve_api_url(cli_value: str | None = None, *, profile: str | None = None) -> str:
    """Apply the precedence chain for the API URL."""
    if cli_value:
        return cli_value.rstrip("/")
    env = os.environ.get(_ENV_API_URL)
    if env:
        return env.rstrip("/")
    config = load_config()
    selected = profile or os.environ.get(_ENV_PROFILE) or config.current_profile
    return config.get_profile(selected).api_url.rstrip("/")


def resolve_token(cli_value: str | None = None, *, profile: str | None = None) -> str | None:
    """Apply the precedence chain for the auth token."""
    if cli_value:
        return cli_value
    env = os.environ.get(_ENV_TOKEN)
    if env:
        return env
    config = load_config()
    selected = profile or os.environ.get(_ENV_PROFILE) or config.current_profile
    return config.get_profile(selected).token
