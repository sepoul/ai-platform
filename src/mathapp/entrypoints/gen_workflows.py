"""Admin command — generate the workflow descriptors and park them in the
blob store for the API to serve.

Runs in an **engine context** (default runtime): it imports every domain
and introspects each graph. Building a JobDefinition does not import
runtime-specific deps like `crewai` (the load-bearing rule), so a single
default-runtime invocation covers every job type.

Re-run after graph/topology changes and as a deploy step:

    python -m mathapp.entrypoints.gen_workflows

The API reads the same blob store, so the descriptors are picked up with
no API restart. Until this runs, `/workflows` is empty (optional surface).
"""
from __future__ import annotations

import json
import logging

from ai_platform.api.workflow_descriptor import WORKFLOWS_BLOB, build_workflow_descriptor
from ai_platform.jobs.bootstrap import register_domains
from ai_platform.workspace.bootstrap import bootstrap_workspace
from ai_platform.workspace.storage.blobs.base import PutFilePayload
from mathapp.composition_root import all_domains

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    ws = bootstrap_workspace()
    domains = register_domains(all_domains(), ws)

    descriptors = {
        name: build_workflow_descriptor(job_def).model_dump(mode="json")
        for name, job_def in domains.job_definitions.items()
    }
    payload = json.dumps(descriptors, indent=2, sort_keys=True).encode("utf-8")

    ws.platform_client.file_repo.put_canonical_file(
        PutFilePayload(
            logical_name=WORKFLOWS_BLOB,
            bytes_data=payload,
            content_type="application/json",
        )
    )
    logger.info(
        "Wrote %d workflow descriptor(s) to blob %s: %s",
        len(descriptors), WORKFLOWS_BLOB, sorted(descriptors),
    )


if __name__ == "__main__":
    main()
