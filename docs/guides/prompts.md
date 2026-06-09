# Prompt registry

Prompts are first-class platform artifacts: versioned pydantic
models, stored alongside the rest of the workspace, editable through
the API, and pulled by graphs at run time. **Never inline prompt
strings inside graph nodes** — see
[AGENTS.md](../AGENTS.md#inline-prompt-strings-in-graph-nodes) for
why.

---

## Layout

| Where | What |
|---|---|
| [`instructions/<domain>/<name>.md`](../instructions/) | The prompt body. Plain markdown; whatever the LLM should read as `instructions`. |
| [`src/ai_platform/ai/prompts/registry.py`](../src/ai_platform/ai/prompts/registry.py) | `PROMPT_DEFINITIONS` — every prompt the platform knows about, paired with its instruction file. |
| [`src/ai_platform/ai/prompts/models.py`](../src/ai_platform/ai/prompts/models.py) | `Prompt`, `PromptSnapshot`, `PromptExecution` — the typed shapes. |
| [`src/ai_platform/workspace/prompt_registry.py`](../src/ai_platform/workspace/prompt_registry.py) | `PromptRegistry` — service layer (`get_prompt`, `update_instructions`, `list_prompts`). |
| [`src/ai_platform/workspace/prompt_repositories.py`](../src/ai_platform/workspace/prompt_repositories.py) | `LocalPromptRepository` / `B2PromptRepository` — backend storage (single-blob). The Supabase variant lives in [`storage/structured/supabase.py`](../src/ai_platform/workspace/storage/structured/supabase.py); see [`storage_backends.md`](../reference/storage-backends.md). |
| [`src/ai_platform/api/routers/prompts.py`](../src/ai_platform/api/routers/prompts.py) | HTTP surface: `GET /prompts`, `GET /prompts/{name}`, `PUT /prompts/{name}`, `GET /prompt-executions/...`. |
| [`src/scripts/deploy_prompts.py`](../src/scripts/deploy_prompts.py) | Deploy script — reads `PROMPT_DEFINITIONS`, get-or-creates each in the registry. |

---

## Adding a new prompt

1. Drop the markdown body at `instructions/<domain>/<name>.md`.
2. Register it in `registry.py`:

   ```python
   _prompt("math_qa", "answer",
           "Solve a math question with a step-by-step plain-prose explanation."),
   ```

   `_prompt(domain, name, description)` reads
   `instructions/<domain>/<name>.md` and returns a `Prompt` with the
   canonical name `"<domain>.<name>"` and version `0.1.0`.

3. Run the deploy script to seed the workspace:

   ```bash
   PYTHONPATH=src BACKEND=local LOCAL_DATA_DIR="$PWD/mathdata" \
     .venv/bin/python src/scripts/deploy_prompts.py --backend local
   ```

   Get-or-create — re-running is a no-op for existing prompts.

4. Pull the prompt at runtime through the graph's deps factory.
   The math_qa domain does this via `_load_prompt` in
   [`src/mathai/math_qa/workflow.py`](../src/mathai/math_qa/workflow.py):

   ```python
   prompt_registry = workspace_client.platform_client.prompt_registry

   def _load_prompt(name: str) -> Optional[str]:
       if prompt_registry is None:
           return None
       try:
           return prompt_registry.get_prompt(name).instructions
       except Exception:
           return None

   def _deps_factory(payload: dict):
       return MathQAWorkflowDependencies(
           ...
           answer_instructions=_load_prompt("math_qa.answer"),
           latex_instructions=_load_prompt("math_qa.latex_render"),
       )
   ```

   Nodes then pass `ctx.deps.answer_instructions` straight to
   `basic_agent(instructions=...)`. No string literal in node code.

---

## Updating an existing prompt

The deploy script is **get-or-create** — it won't overwrite an
existing prompt's instructions. Two paths to update:

- **API** (preferred for live tweaks):
  `PUT /prompts/{name}` with `{ "instructions": "<new body>" }`.
  Bumps the patch version automatically.

- **Code** (preferred when the prompt body lives in git): edit the
  `.md` file, then call `update_instructions` on the registry. There
  isn't a flag-driven `deploy_prompts.py --update` yet — that's an
  open followup. Until it lands, do a one-off:

  ```python
  from mathai.workspace.client import MathWorkspaceClient
  from ai_platform.ai.prompts.registry import PROMPT_DEFINITIONS
  client = MathWorkspaceClient.create(backend="local", root_dir="mathdata")
  svc = client.platform_client.prompt_registry
  for prompt in PROMPT_DEFINITIONS:
      existing = svc.get_prompt(prompt.name)
      if existing.instructions != prompt.instructions:
          svc.update_instructions(prompt.name, prompt.instructions)
  ```

Versions are `MAJOR.MINOR.PATCH`. `update_instructions` bumps the
patch; the registry resolves `get_prompt(name)` to the highest
version automatically.

---

## Open followups

- `deploy_prompts.py --update` to bump versions when the `.md` file
  drifts from the stored copy. Today this is a manual one-off.
- `PromptSnapshot` + `PromptExecution` are out of scope for now — the
  models exist, the API exposes `GET /prompt-executions`, but graphs
  don't write executions yet. Add when we want auditable "what
  prompt + variables ran for this job" trails.
- Variable substitution / typed inputs — current prompts are static
  instructions plus a free-form user prompt. The `Prompt.variables`
  story sketched in the early design has not been built; revisit
  when a prompt actually needs typed inputs.
