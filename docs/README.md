# Documentation

Reference for `ai-platform` — how it works, how to deploy a domain
against it, how to run the platform itself.

## Start here

| | What |
|---|---|
| [`architecture.md`](architecture.md) | System overview with diagrams. Reads top-to-bottom in ~10 min. |

## Concepts — the why

| | What |
|---|---|
| [`concepts/platform-design.md`](concepts/platform-design.md) | Planes, ownership boundaries, vocabulary. The conceptual contract. |
| [`concepts/control-execution-split.md`](concepts/control-execution-split.md) | Why control and execution are separate processes; the import guard. |
| [`concepts/jobs.md`](concepts/jobs.md) | Job lifecycle — states, checkpoints, gates, artifacts. |

## Guides — how to do X

| | What |
|---|---|
| [`guides/deploy-a-domain.md`](guides/deploy-a-domain.md) | Author a `bundle.toml`, build a wheel, `aiplatform deploy` against a running platform. |
| [`guides/prompts.md`](guides/prompts.md) | Add or edit a versioned prompt via the registry. |
| [`guides/live-logs.md`](guides/live-logs.md) | Surface worker progress to the UI via the SSE stream. |

## Reference — config, CLI, contracts

| | What |
|---|---|
| [`reference/storage-backends.md`](reference/storage-backends.md) | `local` / `b2` / `supabase` storage. Choosing and configuring. |
| [`reference/compute-backends.md`](reference/compute-backends.md) | `poll` / `thread` / `celery` compute. Choosing and migrating. |
| [`reference/typed-clients.md`](reference/typed-clients.md) | OpenAPI → TypeScript SDK codegen, the BFF proxy pattern, regen workflow. |

## Operations — running the platform itself

| | What |
|---|---|
| [`operations/hetzner-deploy.md`](operations/hetzner-deploy.md) | The reference single-box deployment. |
| [`operations/supabase.md`](operations/supabase.md) | Postgres + Supabase Storage as the production backend. |

## Project — conventions, roadmap

| | What |
|---|---|
| [`project/README.md`](project/README.md) | What each project doc is. |
| [`project/AGENTS.md`](project/AGENTS.md) | Conventions for coding agents (Claude Code, Cursor, Codex). |
| [`project/NEXT_BEST_STEPS.md`](project/NEXT_BEST_STEPS.md) | Backend backlog, ordered by leverage. |

## Browsable site

Material-themed mkdocs site:

```bash
./scripts/docs.sh   # serves on http://127.0.0.1:8001
.venv/bin/mkdocs build
```

## Where math lives

Math (`math_qa`, `math_conversation`, `math-ui`) is in
[`sepoul/math-app`](https://github.com/sepoul/math-app). It's a
reference domain, not part of the platform — see math-app's own
`docs/` for math-specific design notes.
