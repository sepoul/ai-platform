"""`aip` — the standalone, pure-HTTP ai-platform CLI (issue #49).

Subcommands:
  login              store a profile (API URL [+ token]) for later commands
  deploy             POST a precomputed catalog (+ wheel) over HTTP
  job-definitions    list registered job definitions
  artifact-types     list registered artifact types
  jobs               list jobs (optionally filtered by status / job_type)
  cancel             cancel/reclaim a job (POST /jobs/{id}/cancel)
  snapshot-openapi   write /openapi.json to a file for the SDK-regen workflow

Build the catalog `deploy` consumes with the domain-side
`aiplatform export-manifest` (ships in aiplatform-core), which is the only
step that needs to import the domain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aiplatform_cli import __version__, config as cfg
from aiplatform_cli.api import ApiClient, ApiError
from aiplatform_cli.deploy import deploy_catalog, load_catalog, resolve_wheel_path

_SNAPSHOT_DEFAULT = "openapi.snapshot.json"


def _add_connection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--api-url", default=None, help="Platform API URL (overrides profile/env)")
    p.add_argument("--profile", default=None, help="Config profile to use")
    p.add_argument("--token", default=None, help="Bearer token (overrides profile/env)")


def _client(args: argparse.Namespace) -> ApiClient:
    api_url = cfg.resolve_api_url(getattr(args, "api_url", None), profile=getattr(args, "profile", None))
    token = cfg.resolve_token(getattr(args, "token", None), profile=getattr(args, "profile", None))
    return ApiClient(api_url, token=token)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aip",
        description="Standalone, pure-HTTP CLI for an ai-platform deployment.",
    )
    parser.add_argument("--version", action="version", version=f"aip {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    login = sub.add_parser("login", help="Store an API URL (+ optional token) in a profile")
    login.add_argument("--api-url", required=True, help="Platform API URL to save")
    login.add_argument("--profile", default=cfg.DEFAULT_PROFILE, help="Profile name (default: default)")
    login.add_argument("--token", default=None, help="Bearer token to save with the profile")

    deploy = sub.add_parser("deploy", help="Deploy a precomputed catalog.json (+ wheel) over HTTP")
    deploy.add_argument("--catalog", "-c", default="catalog.json",
                        help="Catalog JSON from `aiplatform export-manifest` (default: ./catalog.json)")
    deploy.add_argument("--wheel", default=None,
                        help="Wheel to upload (default: code_package.wheel, relative to the catalog)")
    deploy.add_argument("--skip-wheel", action="store_true",
                        help="Don't upload the wheel — register definitions/types/prompts only")
    _add_connection_args(deploy)

    jobdefs = sub.add_parser("job-definitions", help="List registered job definitions")
    _add_connection_args(jobdefs)

    arttypes = sub.add_parser("artifact-types", help="List registered artifact types")
    _add_connection_args(arttypes)

    jobs = sub.add_parser("jobs", help="List jobs")
    jobs.add_argument("--status", default=None, help="Filter by status (e.g. RUNNING)")
    jobs.add_argument("--job-type", default=None, help="Filter by job_type")
    _add_connection_args(jobs)

    cancel = sub.add_parser("cancel", help="Cancel / reclaim a job by id")
    cancel.add_argument("job_id", help="Job id to cancel")
    _add_connection_args(cancel)

    workflows = sub.add_parser("workflows", help="List or push workflow descriptors")
    wf_sub = workflows.add_subparsers(dest="wf_action", required=True)
    wf_list = wf_sub.add_parser("list", help="List registered workflow descriptors")
    _add_connection_args(wf_list)
    wf_push = wf_sub.add_parser(
        "push",
        help="Push descriptor JSON (from `gen_workflows --out`) to the platform",
    )
    wf_push.add_argument("--file", "-f", default="workflows.json",
                         help="Descriptors JSON to push (default: ./workflows.json)")
    _add_connection_args(wf_push)

    snapshot = sub.add_parser("snapshot-openapi", help="Write /openapi.json to a file")
    snapshot.add_argument("--out", default=_SNAPSHOT_DEFAULT, help=f"Output path (default: {_SNAPSHOT_DEFAULT})")
    _add_connection_args(snapshot)

    return parser


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _cmd_login(args: argparse.Namespace) -> int:
    path = cfg.login(args.api_url, profile=args.profile, token=args.token)
    suffix = " (with token)" if args.token else ""
    print(f"✓ Saved profile '{args.profile}' → {args.api_url}{suffix}")
    print(f"  {path}")
    return 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    catalog_path = Path(args.catalog)
    try:
        catalog = load_catalog(catalog_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    wheel_path = None
    if not args.skip_wheel:
        wheel_path = Path(args.wheel) if args.wheel else resolve_wheel_path(catalog, catalog_path)

    with _client(args) as client:
        print(f"→ Deploying {catalog_path} to {client.base_url}")
        try:
            report = deploy_catalog(client, catalog, wheel_path=wheel_path, skip_wheel=args.skip_wheel)
        except (ApiError, FileNotFoundError, ValueError) as exc:
            print(f"deploy failed: {exc}", file=sys.stderr)
            return 1

    if report["code_package"]:
        print(f"  ✓ CodePackage:    {report['code_package']}")
    for jd in report["job_definitions"]:
        print(f"  ✓ JobDefinition:  {jd}")
    for at in report["artifact_types"]:
        print(f"  ✓ ArtifactType:   {at}")
    for p in report["prompts"]:
        print(f"  ✓ Prompt:         {p['name']} ({p['action']})")
    print("Done.")
    return 0


def _print_rows(rows: object, *, fields: tuple[str, ...]) -> None:
    items = rows if isinstance(rows, list) else (rows or {}).get("items", [])
    if not items:
        print("  (none)")
        return
    for row in items:
        print("  " + "  ".join(str(row.get(f, "")) for f in fields))


def _cmd_job_definitions(args: argparse.Namespace) -> int:
    with _client(args) as client:
        try:
            rows = client.list_job_definitions()
        except ApiError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    _print_rows(rows, fields=("name", "version", "runtime_selector"))
    return 0


def _cmd_artifact_types(args: argparse.Namespace) -> int:
    with _client(args) as client:
        try:
            rows = client.list_artifact_types()
        except ApiError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    _print_rows(rows, fields=("name", "version", "domain"))
    return 0


def _cmd_jobs(args: argparse.Namespace) -> int:
    with _client(args) as client:
        try:
            rows = client.list_jobs(status=args.status, job_type=args.job_type)
        except ApiError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    _print_rows(rows, fields=("job_id", "job_type", "status"))
    return 0


def _cmd_cancel(args: argparse.Namespace) -> int:
    with _client(args) as client:
        try:
            result = client.cancel_job(args.job_id)
        except ApiError as exc:
            print(f"cancel failed: {exc}", file=sys.stderr)
            return 1
    status = (result or {}).get("status", "CANCELLED")
    print(f"✓ Job {args.job_id} → {status}")
    return 0


def _cmd_workflows(args: argparse.Namespace) -> int:
    if args.wf_action == "list":
        with _client(args) as client:
            try:
                rows = client.list_workflows()
            except ApiError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
        _print_rows(rows, fields=("job_type", "label"))
        return 0

    # push
    path = Path(args.file)
    if not path.exists():
        print(f"error: descriptors file not found: {path}", file=sys.stderr)
        return 2
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: {path} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    # Accept either the raw {job_type: descriptor} map (what `gen_workflows
    # --out` writes) or a {"workflows": {...}} wrapper.
    workflows = loaded.get("workflows", loaded) if isinstance(loaded, dict) else loaded

    with _client(args) as client:
        print(f"→ Pushing {len(workflows)} workflow descriptor(s) from {path} to {client.base_url}")
        try:
            result = client.push_workflows(workflows)
        except ApiError as exc:
            print(f"workflows push failed: {exc}", file=sys.stderr)
            return 1
    for jt in (result or {}).get("job_types", []):
        print(f"  ✓ {jt}")
    print("Done.")
    return 0


def _cmd_snapshot_openapi(args: argparse.Namespace) -> int:
    with _client(args) as client:
        print(f"→ Snapshotting OpenAPI from {client.base_url}")
        try:
            spec = client.get_openapi()
        except ApiError as exc:
            print(f"snapshot-openapi failed: {exc}", file=sys.stderr)
            return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ wrote {out}")
    return 0


_HANDLERS = {
    "login": _cmd_login,
    "deploy": _cmd_deploy,
    "job-definitions": _cmd_job_definitions,
    "artifact-types": _cmd_artifact_types,
    "jobs": _cmd_jobs,
    "cancel": _cmd_cancel,
    "workflows": _cmd_workflows,
    "snapshot-openapi": _cmd_snapshot_openapi,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get(args.cmd)
    if handler is None:  # pragma: no cover — argparse enforces choices
        parser.error(f"unknown command: {args.cmd}")
        return 2
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
