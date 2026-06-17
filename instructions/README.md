# instructions/ — STALE: domain content, belongs in math-app

These are `math_conversation` personae + skill prompts — **domain** content,
not platform content. They predate the math → `sepoul/math-app` split and only
linger here because `docker/Dockerfile.worker` still `COPY`s `instructions/`
into the worker image.

**TODO (domain-level — intentionally NOT done in the root reorg):** relocate
this tree to `sepoul/math-app` (the `math_conversation` domain owns its
prompts), then drop the `COPY instructions` line from `docker/Dockerfile.worker`
so the platform image stops shipping domain prompts. Flagged during the
repo reorg (2026-06).
