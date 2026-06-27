"""Admin command — generate the workflow descriptors for a deployment.

Runs in an **engine context** (it imports domains and introspects each
graph). Two output modes:

    # In-cluster admin path: park the descriptors directly in the blob store
    # the API serves (no API restart needed).
    python -m ai_platform.entrypoints.gen_workflows

    # Deploy-flow path (issue #56): emit descriptors to a JSON file that the
    # standalone CLI transports — `aip workflows push --file workflows.json`.
    python -m ai_platform.entrypoints.gen_workflows --out workflows.json

The stage graphs live in per-runtime execution modules, so a context that
can't import every runtime's deps should scope to its own runtime and let
the API *merge* each contribution (POST /workflows is merge-upsert):

    python -m ai_platform.entrypoints.gen_workflows --runtime crewai --out wf-crewai.json

Until descriptors are generated, `/workflows` is empty (optional surface).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ai_platform.jobs.workflow_descriptor import WORKFLOWS_BLOB, build_descriptors_map
from ai_platform.jobs.bootstrap import (
    register_control_domains,
    register_execution_domains,
)
from ai_platform.workspace.bootstrap import bootstrap_workspace
from ai_platform.workspace.storage.blobs.base import PutFilePayload
from ai_platform.composition_root import (
    control_registers,
    execution_registers_all,
    execution_registers_for_runtime,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _build_descriptors(ws, runtime: str | None) -> dict[str, dict]:
    """`{job_type: descriptor}` for the job types visible in this context.

    Schemas come from the control plane (runtime-agnostic), topology from
    the execution plane. When `runtime` is given, only that runtime's
    executions are imported, so the result is that runtime's subset
    (the API merges subsets across runtimes).
    """
    controls = register_control_domains(control_registers(), ws).job_controls
    registers = (
        execution_registers_for_runtime(runtime)
        if runtime
        else execution_registers_all()
    )
    executions = register_execution_domains(registers, ws).job_executions
    return build_descriptors_map(controls, executions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_workflows",
        description="Generate workflow descriptors and write them to a file or the blob store.",
    )
    parser.add_argument(
        "--runtime",
        default=None,
        help="Only this runtime's job types (default: all). Use per-runtime "
        "when one context can't import every domain's execution deps.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write descriptors JSON to this file (for `aip workflows push`) "
        "instead of parking them in the blob store.",
    )
    args = parser.parse_args(argv)

    ws = bootstrap_workspace()
    descriptors = _build_descriptors(ws, args.runtime)
    blob = json.dumps(descriptors, indent=2, sort_keys=True).encode("utf-8")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(blob + b"\n")
        logger.info(
            "Wrote %d workflow descriptor(s) to %s: %s",
            len(descriptors), out, sorted(descriptors),
        )
        print(f"  ✓ wrote {out}  (push with: aip workflows push --file {out})")
        return 0

    ws.platform_client.file_repo.put_canonical_file(
        PutFilePayload(
            logical_name=WORKFLOWS_BLOB,
            bytes_data=blob,
            content_type="application/json",
        )
    )
    logger.info(
        "Wrote %d workflow descriptor(s) to blob %s: %s",
        len(descriptors), WORKFLOWS_BLOB, sorted(descriptors),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
