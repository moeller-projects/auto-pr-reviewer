# Operator and scheduling workflows

**Purpose:** run ReviewForge container workflows and locate outputs. **Audience:** operators. **Mode:** how-to.

## Cross-platform entrypoints

Use Python on Linux, macOS, or Windows:

```bash
python -m reviewforge.ops build --dry-run
python -m reviewforge.ops run --dry-run --print-command --env-file .env \
  --pr-url https://dev.azure.com/example/project/_git/repo/pullrequest/1 \
  --ado-token placeholder
python -m reviewforge.ops run-open-prs --organization https://dev.azure.com/example/ \
  --projects project --target-branches main --dry-run
```

`build`, `run`, and `run-open-prs` choose Docker then Podman unless
`--runtime` is supplied. Explicit flags override environment variables, and
the chosen `--env-file` is passed directly to the container. `--print-command`
previews a single-review invocation without spawning a container.

`run-open-prs` keeps batch selection semantics: `--max-pull-requests` caps
the sorted matching set before review, and `--interactive` accepts `all`,
`none`, comma-separated indexes, and inclusive ranges such as `1,3-5`.

## PowerShell compatibility

`build.ps1`, `run.ps1`, and `run-open-prs.ps1` now forward to the Python
entrypoints. They remain for existing Windows operators and scheduled tasks,
but new automation should invoke `python -m reviewforge.ops`.

`setup-open-prs-schedule.ps1` remains Windows Task Scheduler integration; it
continues to invoke the batch compatibility wrapper.

## Scheduled open-PR runs

`setup-open-prs-schedule.ps1` registers the task with the repository root as
its working directory and re-registers an existing task when run again. The
scheduled wrapper resolves Python deterministically: it uses `uv run
--project <repo>` when `uv` is available, otherwise it uses the repository's
synced `.venv` (`.venv/Scripts/python.exe` on Windows or `.venv/bin/python`
on POSIX). If neither exists, setup fails instead of falling back to a bare
`python`.

Scheduled credentials and discovery settings come from the `.env` file
referenced by `-EnvFile`; the wrapper loads it before each run. Never pass
`-AdoToken` to the scheduled task: tokens must not be stored in Task
Scheduler arguments or XML. Re-run `setup-open-prs-schedule.ps1` after
changing the task's `-EnvFile`, script path, or other registration settings;
it unregisters and re-registers the task.

## Artifacts and posting

Review output is written under `REVIEW_ARTIFACT_ROOT/pr-<PR_ID>/runs/<RUN_ID>/`. Read `run.log` there for the chronological, redacted container log for that run; `pr-<PR_ID>/latest.txt` identifies the latest run directory. Preserve `run-summary.json`, `review-result.json`, and `final-findings.json` when diagnosing or reposting. The container volume is already mounted by `run.ps1` and `run-open-prs.ps1`, so the same path is available to PowerShell operators. Do not edit the `prb:` deduplication marker in posted comment bodies; see [ADO integration](../reference/ado-integration.md).

## CRG graph cache

With `CRG_ENABLED=1`, the Tree-sitter knowledge graph persists across runs at `CRG_CACHE_DIR/<repo_id>/crg-<tool_version>/crg.db`. Container runs mount the dedicated named volume `reviewforge-crg-cache` (override with `REVIEW_CRG_CACHE_VOLUME_NAME`) at `/workspace/crg-cache` and set `CRG_CACHE_DIR` accordingly; local runs default to `REVIEW_ARTIFACT_ROOT/crg-cache`. The first run for a repository performs a full build (seconds to tens of seconds depending on repo size); subsequent runs apply an incremental update, typically under two seconds — watch for `CRG graph incremental build` vs `CRG graph full build` in `run.log`. Upgrading `code-review-graph` changes the version-keyed directory and costs exactly one cold rebuild. To force a cold rebuild manually, delete the repo's `crg-<version>` directory from the volume (`attach-volume.ps1` mounts the artifact volume for inspection; use `--volume reviewforge-crg-cache:/workspace/crg-cache` for the cache volume).


When `GRAPH_API_DIFF=1`, immutable base snapshots are cached under
`CRG_CACHE_DIR/<repo-id>/crg-<version>/base-snapshots/<base-sha>.json`.
The first run for a new base SHA pays one disposable worktree graph build;
reruns reuse the snapshot. `GRAPH_FLOWS=1` and `GRAPH_ARCH=1` add only warm
Python-side analysis and degrade independently when optional graph data is
unavailable.