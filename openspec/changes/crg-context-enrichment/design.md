## Context

The single-pi reasoning engine spends part of its budget on ad-hoc file reads
and grep exploration to discover what changed, who calls it, and whether tests
cover it. The `code-review-graph` (CRG) package provides that deterministically
from a Tree-sitter/SQLite knowledge graph. The review pipeline already checks
out the PR working tree in `PrepareRepositoryStage`, so the graph can be built
without any model or network involvement.

The checkout is shallow and disposable (`tempfile.mkdtemp`, deleted after the
run), and containers run with `--rm`. Anything that must survive across runs
has to live on a mounted volume.

## Design

A new `EnrichWithCrgStage` runs between `PrepareRepositoryStage` and
`ExecuteReasoningEngineStage` in every pipeline that executes a reasoning
engine. It is always registered and self-skips unless `CRG_ENABLED` is set or
the review mode is `no_op`.

Graph persistence:

- The SQLite DB lives at `<cache-root>/<repo_id>/crg-<tool_version>/crg.db`.
  The cache root defaults to `<review_artifact_root>/crg-cache` (inside the
  artifact volume) and is overridable with `CRG_CACHE_DIR`. Container runs
  mount a dedicated named volume (`reviewforge-crg-cache`, overridable via
  `REVIEW_CRG_CACHE_VOLUME_NAME`) at `/workspace/crg-cache` and receive
  `CRG_CACHE_DIR=/workspace/crg-cache`.
- The cold/warm decision is made by testing `db_path.exists()` **before**
  constructing `GraphStore`, because opening the store creates the file
  eagerly. First run: `full_build`. Later runs: `incremental_update` with the
  PR's changed-file list passed explicitly (the package default of diffing
  `HEAD~1` is unreliable in shallow, detached checkouts). Any incremental
  failure falls back to one full build.
- Keying the path by the CRG tool version makes an upgrade cost exactly one
  cold rebuild instead of risking an incompatible graph.

Analysis and contract:

- `analyze_changes` runs with the pipeline's changed files and diff line
  ranges; `include_churn` stays off (shallow clone).
- The result is wrapped in the canonical `crg-analysis.json` document:
  `status` (`ok`/`degraded`/`failed`), `tool_version`,
  `build{mode,duration_ms}`, `summary`, `risk_score`, `changed_functions`,
  `affected_flows`, `test_gaps`, `impacted_files`, `review_priorities`.
  The package's 500-function truncation flag surfaces as `status: "degraded"`.
- Every failure path (package missing, build error, analysis error) logs a
  warning, writes the artifact with `status: "failed"`, and returns normally.
  The stage never raises.

Prompt injection:

- `_build_single_pi_prefix` appends a "Deterministic graph context" section
  before the diff, only for `ok`/`degraded` documents. Ordering is
  deterministic (risk desc, path asc) with bounded subsections (5 priorities /
  15 functions / 30 paths / 15 test gaps) and a UTF-8-safe byte cap from
  `CRG_CONTEXT_MAX_BYTES` (default 8192). Absent or failed analyses leave the
  instruction byte-identical to the pre-integration shape.
- The block lives in the shared prefix, so chunked reviews include it in
  chunk 1 only (it repeats per chunk only when Pi session reuse is disabled
  and the whole shared prefix repeats — pre-existing behavior).

Boundaries:

- CRG is invoked Python-side only. No MCP server, no daemon, no new model
  tools; `ModelRunner` and the Pi `--tools read,grep` read-only sandbox are
  untouched.
- `code-review-graph` is pinned exactly (`==2.3.7`) in `pyproject.toml` under
  the `crg` extra and locked in `uv.lock`; the image installs it via
  `uv export --extra crg`. No other new dependencies.

## Risks

- Warm updates rely on the pipeline's changed-file list; files changed by
  outside edits between runs on the same checkout are irrelevant because each
  run gets a fresh checkout and re-analyses the full PR file set.
- A corrupt DB surfaces as an incremental failure and costs one fallback full
  build; the next run is warm again.
