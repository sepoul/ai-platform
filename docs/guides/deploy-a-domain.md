# Deploy a domain

Read this if you're packaging a domain (math, your friend's, your own)
to run against a running ai-platform instance. End-to-end, deploying a
domain is:

1. Author a `bundle.toml` next to your domain package.
2. Build the wheel.
3. Run `aiplatform deploy` against the platform's API URL.
4. Restart the platform's workers — they install your wheel from the
   catalog and start serving your jobs.

No platform code changes. No image rebuild. Catalog-driven discovery
([architecture.md §6](../architecture.md#6-platform-and-domain-are-separate-everywhere))
makes this work.

## Prereqs

A domain package shaped like this (see `packages/_demo/` in this repo,
or [math-app's packages](https://github.com/sepoul/math-app/tree/main/packages)
for working examples):

```
your_domain/
  pyproject.toml
  bundle.toml                   ← what aiplatform deploy reads
  src/your_domain/
    __init__.py
    control.py                  ← register_control(ctx) -> ControlDomain
    execution.py                ← register_execution(ctx) -> ExecutionDomain
    models.py                   ← BaseJobInput / BaseJobResult subclasses
    artifacts.py                ← BaseArtifact subclasses
    workflow.py                 ← your pydantic_graph nodes
    state.py                    ← BaseJobState subclass
```

`pyproject.toml` must declare an `[execution]` extra carrying the
runtime stack (LLM SDKs, etc.):

```toml
[project]
name = "mathai-math-qa"
version = "0.1.0"
dependencies = ["aiplatform-core"]

[project.optional-dependencies]
# Pulled in when the worker pip-installs the wheel at boot.
execution = ["pydantic-ai-slim[anthropic,duckduckgo,logfire]>=1.58.0"]
```

The `[execution]` extra is a convention: the worker's catalog install
pass calls `pip install <wheel>[execution]` so the runtime deps land.

## Author `bundle.toml`

Place it at the package root:

```toml
[package]
name    = "mathai-math-qa"                          # distribution name (matches wheel)
version = "0.1.0"
runtime = "default"                                  # "default" | "crewai"
wheel   = "dist/mathai_math_qa-0.1.0-py3-none-any.whl"

[control]
domain               = "math_qa"
control_entrypoint   = "mathai.math_qa.control:register_control"
execution_entrypoint = "mathai.math_qa.execution:register_execution"
```

Fields:

- **`package.runtime`** — pins which worker pool serves your jobs.
  Today: `default` (pydantic-ai-slim + Logfire, otel ≥ 1.39) or
  `crewai` (crewai\[anthropic\], otel < 1.35). Otel pin conflict means
  the two stacks can't share an interpreter, so they run as separate
  pools.
- **`package.wheel`** — path to your wheel, relative to the
  `bundle.toml` location.
- **`control.control_entrypoint`** — imported in-process by the
  `aiplatform deploy` CLI so it can introspect your JobControls and
  artifact types. Must be engine-free (no pydantic_ai / crewai
  imports at module top).
- **`control.execution_entrypoint`** — stored on the JobDefinition
  catalog row. The worker resolves it after pip-installing the wheel.

## Build the wheel

```bash
cd path/to/your_domain
uv build --wheel
```

Produces `dist/mathai_math_qa-0.1.0-py3-none-any.whl`.

## Deploy

```bash
# CLI is on PATH after `pip install aiplatform-core`
uv run aiplatform deploy \
    --bundle bundle.toml \
    --api-url http://your-platform:8000
```

What the CLI does (idempotent on `(name, version)`):

1. POST the wheel bytes to `/code-packages` — they're stored under
   the platform's FileRepository + a `CodePackageRecord` row records
   sha256 + size + runtime + filename.
2. Import `control_entrypoint`. Each JobControl returned gets POSTed
   to `/job-definitions` with its schemas + your `code_entrypoint`.
3. Each `BaseArtifact` subclass declared by the domain gets POSTed
   to `/artifact-types` with its JSON Schema.

Output:

```
→ Deploying bundle.toml to http://your-platform:8000
  ✓ CodePackage:    mathai-math-qa@0.1.0
  ✓ JobDefinition:  math_qa@0.1.0
  ✓ ArtifactType:   math_question@0.1.0
  ✓ ArtifactType:   ai_answer@0.1.0
  …
Done.
```

## Restart workers

Workers detect new CodePackage rows at boot. Restart your worker pool
matching your `package.runtime`:

```bash
# On the platform box
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    restart worker
# For crewai-runtime domains:
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    restart worker-crewai
```

Watch the boot logs — you should see (e.g. for default runtime):

```
[INFO] code_package_install: Installed CodePackage mathai-math-qa@0.1.0
[INFO] worker: execution_registers_from_catalog returned 1 register(s)
       for runtime=default — catalog-driven discovery active
[INFO] worker: Worker worker-1 runtime=default serving job types: ['math_qa']
```

The wheel is pip-installed into the running interpreter. No image
rebuild required.

## Submit a test job

```bash
curl -X POST -H 'content-type: application/json' \
    -d '{"job_type":"math_qa","question_text":"What is 2+2?"}' \
    http://your-platform:8000/jobs/runs/submit
```

Or use the platform-ui's submit form (auto-generated from your
JobDefinition's `input_schema`).

## CI: deploy on every push

A reference deploy workflow lives at
[math-app/.github/workflows/deploy.yml](https://github.com/sepoul/math-app/blob/main/.github/workflows/deploy.yml).
It:

1. Checks out the domain repo + the platform repo side-by-side (the
   CLI needs `aiplatform-core` installable).
2. Builds the wheels with `uv build --wheel`.
3. Runs `aiplatform deploy` for each `bundle.toml`, with
   `PLATFORM_API_URL` from a repo secret or var.

The CI's only environmental requirement is network access to
`PLATFORM_API_URL`. If your platform is behind Tailscale or a private
network, use `tailscale/github-action` or a self-hosted runner.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `aiplatform: command not found` | `aiplatform-core` not installed. `uv pip install -e <path-to-aiplatform-core>` or install from the git URL. |
| `deploy failed: No module named ...` | The `control_entrypoint` module isn't importable from the CLI's Python env. Install your domain package + the platform's core first. |
| Boot logs show "Installed CodePackage X" but worker doesn't serve the job | `code_entrypoint` doesn't resolve. Check that the wheel actually contains the module path you set. |
| Boot logs show "Failed to install CodePackage X" with pip stderr | Surface the pip stderr verbatim in the log. Usually: missing transitive dep, or the wheel is invalid. |

## Reading next

- [`../architecture.md`](../architecture.md) — system overview
- [`../concepts/control-execution-split.md`](../concepts/control-execution-split.md) — why control and execution are split
- [`../concepts/jobs.md`](../concepts/jobs.md) — job lifecycle, gates, artifacts
