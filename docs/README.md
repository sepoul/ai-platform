# Docs index

Operational and onboarding references for `mathapp` and the
`math-ui` companion. Roadmap-y stuff lives in
[`../FEATURES.md`](../FEATURES.md) and the two
`NEXT_BEST_STEPS.md` files; this directory is for **how things
already work**.

For a browsable rendered version, run `./scripts/docs.sh` and open
<http://127.0.0.1:8001>. Material theme, full-text search, dark
mode, live reload while you edit. CLI build:
`.venv/bin/mkdocs build`.

| Doc | Read it when |
|---|---|
| [`dev_lifecycle.md`](dev_lifecycle.md) | Touching anything that crosses the FastAPI ↔ Next.js boundary — codegen loop, what to regenerate, common drift scenarios. |
| [`onboarding_new_job_type.md`](onboarding_new_job_type.md) | Adding a new domain workflow. Walks through the `JobDefinition` you write and the registry entries that pick it up. |
| [`jobs_spec.md`](jobs_spec.md) | Working at the platform level — job lifecycle, checkpoints, gates, artifacts, the runner's invariants. |
| [`compute_backends.md`](compute_backends.md) | Switching between `poll` / `thread` / `celery`, or implementing a new one. |
| [`prompt_registry.md`](prompt_registry.md) | Adding or editing an agent prompt. Prompts live in the registry, not as string literals in graph nodes. |
| [`live_logs.md`](live_logs.md) | Surfacing real-time progress from a worker to the UI via the SSE stream. |
| [`math_qa_stabilization_plan.md`](math_qa_stabilization_plan.md) | The rollout order for the larger Math Q&A artifact rework. Companion to [`../FEATURES.md`](../FEATURES.md). |

If a coding agent (Cursor, Claude Code, Codex, etc.) is editing
this repo, point it at [`../AGENTS.md`](../AGENTS.md) first — it
links here from the right places.
