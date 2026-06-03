"""`aiplatform` CLI entrypoint — currently only `deploy`.

Installed via the `aiplatform` script entry on `aiplatform-core`.
Usage from a friend's repo:

    aiplatform deploy                                # bundle.toml in CWD
    aiplatform deploy --bundle path/to/bundle.toml --api-url http://my.platform

Single command, three HTTP calls (idempotent): wheel upload →
JobDefinitions → ArtifactTypes. See [[bundle.deploy_bundle]] for the
orchestration shape; this module is a thin argparse + pretty-print
wrapper around it.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ai_platform.bundle import DEFAULT_API_URL, deploy_bundle


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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "deploy":
        return _cmd_deploy(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2  # unreachable; argparse.error exits


if __name__ == "__main__":
    sys.exit(main())
