#!/usr/bin/env python3
"""Deploy v0 prompt definitions to the prompt repository.

Uses get-or-create semantics: existing prompts are left untouched,
missing prompts are created. Safe to re-run (idempotent).

Usage:
    python deploy_prompts.py --backend local --data-dir /tmp/test_prompts
    python deploy_prompts.py --backend b2
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from ai_platform.ai.prompts.registry import PROMPT_DEFINITIONS
from ai_platform.workspace.client import PlatformClient
from ai_platform.workspace.storage.backends import make_backend
from ai_platform.workspace.storage.exceptions import ObjectNotFound

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy prompt definitions")
    parser.add_argument(
        "--backend",
        default="local",
        choices=["b2", "local"],
        help="Storage backend (default: local)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Local data directory (only for --backend local)",
    )
    args = parser.parse_args()

    os.environ["BACKEND"] = args.backend
    if args.data_dir:
        os.environ["LOCAL_DATA_DIR"] = args.data_dir

    backend = make_backend(args.backend, root_dir=args.data_dir)
    platform_client = PlatformClient.from_backend(backend)
    svc = getattr(platform_client, "prompt_registry", None)
    if svc is None:
        logger.error("Prompt registry not available on this client")
        sys.exit(1)

    created = 0
    skipped = 0
    for prompt in PROMPT_DEFINITIONS:
        try:
            svc.get_prompt(prompt.name)
            skipped += 1
            logger.info("EXISTS  %s", prompt.name)
        except ObjectNotFound:
            svc.get_or_create(prompt)
            created += 1
            logger.info("CREATED %s (v%s)", prompt.name, prompt.version)

    logger.info("Done. %d created, %d already existed. Total: %d", created, skipped, len(PROMPT_DEFINITIONS))


if __name__ == "__main__":
    main()
