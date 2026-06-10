"""`aiplatform` CLI entrypoint — `deploy` and `declare-artifacts`.

Installed via the `aiplatform` script entry on `aiplatform-core`.
Usage from a friend's repo:

    aiplatform deploy                                # bundle.toml in CWD
    aiplatform deploy --bundle path/to/bundle.toml --api-url http://my.platform

    # Contract-first: publish just the artifact types, before the wheel
    # or job exists, so the SDK can regenerate and UI/backend build in
    # parallel (see sdk-contract-first-plan.md).
    aiplatform declare-artifacts --bundle bundle.toml --api-url http://my.platform

`deploy` = wheel upload → JobDefinitions → ArtifactTypes (idempotent).
`declare-artifacts` = ArtifactTypes only. See [[bundle.deploy_bundle]] /
[[bundle.declare_artifacts]]; this module is a thin argparse +
pretty-print wrapper.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_platform.bundle import DEFAULT_API_URL, declare_artifacts, deploy_bundle


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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "deploy":
        return _cmd_deploy(args)
    if args.cmd == "declare-artifacts":
        return _cmd_declare_artifacts(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable; argparse.error exits


if __name__ == "__main__":
    sys.exit(main())
