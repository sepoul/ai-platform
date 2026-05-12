"""Generate the API reference tree at build time.

Walks `src/`, emits one markdown stub per module under
`docs/reference/<package>/<module>.md` with a single
`::: <dotted.path>` directive. `mkdocstrings` then renders
docstrings, signatures, and source on each page; `mkdocs-literate-nav`
folds the resulting `SUMMARY.md` into the sidebar so the nav mirrors
the package layout.

Skips `__main__` and `__pycache__`. `__init__` files become the
`index.md` for their package, so a folder navigates straight to its
top-level module docstring.
"""
from __future__ import annotations

from pathlib import Path

import mkdocs_gen_files


SRC = Path("src")
REFERENCE = Path("reference")
nav = mkdocs_gen_files.Nav()


with mkdocs_gen_files.open(REFERENCE / "index.md", "w") as fd:
    fd.write(
        "# API reference\n\n"
        "Auto-generated from the docstrings under `src/`. One page per\n"
        "module, mirroring the package layout. The four top-level packages:\n\n"
        "- **`ai_platform`** — generic platform primitives (jobs, workflows,\n"
        "  prompts, artifacts, runtime, compute backends). Domain code never\n"
        "  imports from anywhere else, but everything else may import from\n"
        "  here.\n"
        "- **`mathai`** — the `math_qa` domain. Plugs into the platform via\n"
        "  `Domain.register()`.\n"
        "- **`mathapp`** — composition root + entrypoints (the API process,\n"
        "  the worker process).\n"
        "- **`scripts`** — one-shot CLI tools (prompt deploy, etc.).\n\n"
        "Pages with empty bodies have no docstrings yet — adding them is the\n"
        "next iteration.\n"
    )

for path in sorted(SRC.rglob("*.py")):
    module_path = path.relative_to(SRC).with_suffix("")
    doc_path = path.relative_to(SRC).with_suffix(".md")
    full_doc_path = REFERENCE / doc_path

    parts = tuple(module_path.parts)

    if parts[-1] == "__init__":
        parts = parts[:-1]
        if not parts:
            continue
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")
    elif parts[-1] == "__main__":
        continue

    nav[parts] = doc_path.as_posix()

    ident = ".".join(parts)
    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        fd.write(f"# `{ident}`\n\n::: {ident}\n")

    mkdocs_gen_files.set_edit_path(full_doc_path, path)

with mkdocs_gen_files.open(REFERENCE / "SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
