# aiplatform-cli (`aip`)

A standalone, **pure-HTTP** control/ops CLI for an ai-platform deployment —
in the spirit of `gh` / `az` / `databricks`. It talks to the platform only
over its OpenAPI surface and imports **zero** platform internals (no
`ai_platform`, no storage backends, no in-process domain import). So it
installs and versions independently of the server:

```bash
pipx install aiplatform-cli
```

This is issue #49: a deploy/ops tool should depend on the API *contract*,
not the API's source. (The TS SDK already does this for the read path; this
is the same philosophy for the write/ops path.)

## The deploy split

A pure-HTTP tool can't introspect a domain's JobDefinition / ArtifactType
schemas. That one step lives in the **domain's** venv (which has
`aiplatform-core` + the domain installed) and emits a plain-JSON *catalog*:

```bash
# domain-side build (ships in aiplatform-core)
aiplatform export-manifest --bundle bundle.toml -o catalog.json
```

The CLI then replays that catalog over HTTP — no domain import:

```bash
aip login --api-url https://my-platform:8000
aip deploy --catalog catalog.json            # uploads wheel + POSTs catalog
```

## Commands

| Command | What it does |
|---|---|
| `aip login --api-url URL [--token T] [--profile P]` | Save a profile to `~/.config/aiplatform/config.json` |
| `aip deploy --catalog catalog.json [--wheel W] [--skip-wheel]` | Upload wheel + POST job-definitions / artifact-types / prompts |
| `aip job-definitions` | List registered job definitions |
| `aip artifact-types` | List registered artifact types |
| `aip jobs [--status S] [--job-type T]` | List jobs |
| `aip cancel JOB_ID` | Cancel / reclaim a job (`POST /jobs/{id}/cancel`) |
| `aip snapshot-openapi [--out PATH]` | Dump `/openapi.json` for the SDK-regen workflow |

### Connection resolution

For every command, the API URL and token resolve in this order:

1. CLI flag — `--api-url` / `--token`
2. env — `AIPLATFORM_API_URL` / `AIPLATFORM_TOKEN`
3. the selected profile (`--profile`, `AIPLATFORM_PROFILE`, or the current one)
4. (URL only) the built-in default `http://127.0.0.1:8000`

Config location override: `AIPLATFORM_CONFIG_DIR`.
