# Project — practices, ambition, backlog

These files live at repo root (and the math-ui repo root) so they
stay first-class for `git` / GitHub reviewers; they're surfaced
here for browsing convenience. They are **not** architecture
documentation — they describe how the team works on the codebase
and where it's going next.

| File | Lives at | What it is |
|---|---|---|
| [AGENTS.md](AGENTS.md) | `mathapp/AGENTS.md` | Conventions for coding agents (Cursor, Claude Code, Codex). Red flags + the right way to do the thing. |
| [FEATURES.md](FEATURES.md) | `mathapp/FEATURES.md` | Directional ideas — uncommitted designs, where the platform might go. Source of truth for design intent. |
| [NEXT_BEST_STEPS.md](NEXT_BEST_STEPS.md) | `mathapp/NEXT_BEST_STEPS.md` | Backend backlog. ✅-done entries record what landed and where. |

The frontend keeps its own `NEXT_BEST_STEPS.md` in the
[`ai-platform-ui`](https://github.com/sepoul/ai-platform-ui) repo.

For *how things actually work* (the implementation reference), see
the rest of [`docs/`](../README.md).
