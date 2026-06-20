"""`aiplatform` CLI entrypoint — `deploy` and `declare-artifacts`.

Installed via the `aiplatform` script entry on `aiplatform-core`.
Usage from a friend's repo:

    aiplatform deploy                                # bundle.toml in CWD
    aiplatform deploy --bundle path/to/bundle.toml --api-url http://my.platform

    # Contract-first: publish just the artifact types, before the wheel
    # or job exists, so the SDK can regenerate and UI/backend build in
    # parallel (see sdk-contract-first-plan.md).
    aiplatform declare-artifacts --bundle bundle.toml --api-url http://my.platform

    # Dump a deployment's OpenAPI for the SDK-regen workflow. Run where
    # you can reach the box (e.g. on the tailnet); commit the result.
    aiplatform snapshot-openapi --api-url http://mathapp-prod:8000

`deploy` = wheel upload → JobDefinitions → ArtifactTypes (idempotent).
`declare-artifacts` = ArtifactTypes only. `snapshot-openapi` = write the
full `/openapi.json` to a file so CI can regenerate types without any
privileged network access. See [[bundle.deploy_bundle]] /
[[bundle.declare_artifacts]] / [[bundle.snapshot_openapi]]; this module is
a thin argparse + pretty-print wrapper.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_platform.bundle import (
    DEFAULT_API_URL,
    declare_artifacts,
    deploy_bundle,
    deploy_prompts,
    snapshot_openapi,
)


_SNAPSHOT_DEFAULT = "sdk-ts/openapi.snapshot.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiplatform",
        description="Deploy a bundle (code + job definitions + artifact types) to a running ai-platform instance.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    deploy = sub.add_parser("deploy", help="Deploy a bundle.toml to the platform")
    deploy.add_argument(
        "--bundle",
        default="bundle.toml",
        help="Path to the bundle manifest (default: ./bundle.toml)",
    )
    deploy.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Platform API URL (default: {DEFAULT_API_URL})",
    )

    declare = sub.add_parser(
        "declare-artifacts",
        help="Register only a bundle's artifact types (the contract) — no wheel, no job",
    )
    declare.add_argument(
        "--bundle",
        default="bundle.toml",
        help="Path to the bundle manifest (default: ./bundle.toml)",
    )
    declare.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Platform API URL (default: {DEFAULT_API_URL})",
    )

    prompts = sub.add_parser(
        "deploy-prompts",
        help="Deploy a bundle's prompts (the [prompts] instructions dir) to /prompts",
    )
    prompts.add_argument(
        "--bundle",
        default="bundle.toml",
        help="Path to the bundle manifest (default: ./bundle.toml)",
    )
    prompts.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Platform API URL (default: {DEFAULT_API_URL})",
    )

    snapshot = sub.add_parser(
        "snapshot-openapi",
        help="Dump a deployment's /openapi.json to a file for the SDK-regen workflow",
    )
    snapshot.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"Platform API URL to snapshot (default: {DEFAULT_API_URL})",
    )
    snapshot.add_argument(
        "--out",
        default=_SNAPSHOT_DEFAULT,
        help=f"Where to write the snapshot (default: {_SNAPSHOT_DEFAULT})",
    )
    return parser


def _cmd_deploy(args: argparse.Namespace) -> int:
    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"error: bundle manifest not found: {bundle_path}", file=sys.stderr)
        return 2

    print(f"→ Deploying {bundle_path} to {args.api_url}")
    try:
        report = deploy_bundle(bundle_path, api_url=args.api_url)
    except Exception as exc:  # noqa: BLE001 — top-level CLI surface
        print(f"deploy failed: {exc}", file=sys.stderr)
        return 1

    print(f"  ✓ CodePackage:    {report['code_package']}")
    for jd in report["job_definitions"]:
        print(f"  ✓ JobDefinition:  {jd}")
    for at in report["artifact_types"]:
        print(f"  ✓ ArtifactType:   {at}")
    print("Done.")
    return 0


def _cmd_declare_artifacts(args: argparse.Namespace) -> int:
    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"error: bundle manifest not found: {bundle_path}", file=sys.stderr)
        return 2

    print(f"→ Declaring artifact types from {bundle_path} to {args.api_url}")
    try:
        report = declare_artifacts(bundle_path, api_url=args.api_url)
    except Exception as exc:  # noqa: BLE001 — top-level CLI surface
        print(f"declare-artifacts failed: {exc}", file=sys.stderr)
        return 1

    artifact_types = report["artifact_types"]
    if not artifact_types:
        print("  (no artifact types declared by this bundle)")
    for at in artifact_types:
        print(f"  ✓ ArtifactType:   {at}")
    print("Done.")
    return 0


def _cmd_deploy_prompts(args: argparse.Namespace) -> int:
    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"error: bundle manifest not found: {bundle_path}", file=sys.stderr)
        return 2

    print(f"→ Deploying prompts from {bundle_path} to {args.api_url}")
    try:
        report = deploy_prompts(bundle_path, api_url=args.api_url)
    except Exception as exc:  # noqa: BLE001 — top-level CLI surface
        print(f"deploy-prompts failed: {exc}", file=sys.stderr)
        return 1

    prompts = report["prompts"]
    if not prompts:
        print("  (no prompts declared by this bundle — add a [prompts] section)")
    for name in prompts:
        print(f"  ✓ Prompt:  {name}")
    print("Done.")
    return 0


def _cmd_snapshot_openapi(args: argparse.Namespace) -> int:
    print(f"→ Snapshotting OpenAPI from {args.api_url}")
    try:
        out = snapshot_openapi(args.api_url, out_path=args.out)
    except Exception as exc:  # noqa: BLE001 — top-level CLI surface
        print(f"snapshot-openapi failed: {exc}", file=sys.stderr)
        return 1
    print(f"  ✓ wrote {out}")
    print("Commit it — the SDK-regen workflow regenerates schema.d.ts from it.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "deploy":
        return _cmd_deploy(args)
    if args.cmd == "declare-artifacts":
        return _cmd_declare_artifacts(args)
    if args.cmd == "deploy-prompts":
        return _cmd_deploy_prompts(args)
    if args.cmd == "snapshot-openapi":
        return _cmd_snapshot_openapi(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable; argparse.error exits


if __name__ == "__main__":
    sys.exit(main())
