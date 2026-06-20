"""bundle.toml — the declarative manifest for `aiplatform deploy`.

Schema (validated via pydantic):

    [package]
    name             = "mathai-math-qa"             # distribution name (matches the wheel's)
    version          = "1.0.0"
    runtime          = "default"                    # "default" | "crewai"
    wheel            = "dist/mathai_math_qa-1.0.0-py3-none-any.whl"

    [control]
    domain               = "math_qa"                                          # also used as ArtifactType.domain
    control_entrypoint   = "mathai.math_qa.control:register_control"          # imported at deploy time
    execution_entrypoint = "mathai.math_qa.execution:register_execution"      # written into the JobDefinition row

`control_entrypoint` is loaded in-process by the deploy CLI to
introspect the JobControls + artifact types. `execution_entrypoint`
is **not** loaded — it's recorded on the JobDefinition row and
resolved by the worker after it pip-installs the wheel.

Versioning intent: `package.version` is the wheel's version (drives
the CodePackage catalog row). JobDefinitions + ArtifactTypes default
to the same version unless overridden — we don't expose the override
yet because no caller has needed it; add it when one does.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict


# tomllib is stdlib on 3.11+; this repo targets 3.13.
if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover — unreachable under our requires-python
    raise RuntimeError("aiplatform deploy requires Python 3.11+ for tomllib")


class PackageSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str = "1.0.0"
    runtime: str  # validated against KNOWN_RUNTIMES at deploy time
    wheel: str    # path relative to the bundle.toml file


class ControlSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    control_entrypoint: str  # "package.module:callable"
    execution_entrypoint: str


class PromptsSection(BaseModel):
    """Optional — declares a domain's deployable prompts (instructions).

        [prompts]
        dir    = "instructions"   # path relative to bundle.toml
        domain = "math_qa"        # grouping key for the deployed prompts

    `aiplatform deploy-prompts` walks `dir` and POSTs each `.md` to
    `/prompts` (see `load_prompts_from_dir` for the naming convention).
    """
    model_config = ConfigDict(extra="forbid")

    dir: str
    domain: str


class BundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package: PackageSection
    control: ControlSection
    prompts: PromptsSection | None = None

    @classmethod
    def load(cls, path: str | Path) -> "BundleManifest":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"bundle manifest not found: {p}")
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        return cls.model_validate(raw)

    def wheel_path(self, manifest_path: str | Path) -> Path:
        """Resolve `package.wheel` relative to the manifest file."""
        base = Path(manifest_path).resolve().parent
        return (base / self.package.wheel).resolve()
