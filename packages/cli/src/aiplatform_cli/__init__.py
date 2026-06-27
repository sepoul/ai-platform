"""aiplatform-cli — a thin, standalone control/ops CLI for the ai-platform.

In the spirit of `gh` / `az` / `databricks`: it talks to a platform
deployment **only over HTTP** (the OpenAPI surface) and imports **zero**
platform internals — no `ai_platform`, no storage backends, no in-process
domain import. That's the whole point (issue #49): the deploy/ops tool
depends on the API *contract*, not the API's source, so it installs and
versions independently (`pipx install aiplatform-cli`) and never trips the
platform's import-time landmines.

The one thing a pure-HTTP tool can't do — introspect a domain's
JobDefinition / ArtifactType schemas — is split out to a domain-side
build step (`aiplatform export-manifest`, shipped in `aiplatform-core`)
that emits a plain-JSON *catalog*. This CLI consumes that catalog and
POSTs it; it never imports the domain.

Console script: ``aip``.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
