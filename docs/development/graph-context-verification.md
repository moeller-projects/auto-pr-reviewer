# Graph-context (CRG) integration — verification report
> Module layout note: current CRG implementation lives under `src/reviewforge/pipeline/crg/`; the dated paths below are historical audit references.

**Purpose:** record the audit of the CRG integration against the
implementation plan, the root cause of the cross-run persistence defect, and
the fixes applied. **Audience:** maintainers and reviewers of the CRG work.
**Mode:** reference / decision record. **Date:** 2026-07-26.

> Naming note. The audited plan uses the names `collect_graph_context`,
> `graph-context.json`, `GRAPH_CONTEXT`, `GRAPH_CACHE_DIR`,
> `GRAPH_CONTEXT_MAX_BYTES`, and `graph-cache/<repo-slug>/crg-<version>`. The
> implementation that landed (openspec change `crg-context-enrichment`) uses
> the equivalent names `enrich_with_crg` / `EnrichWithCrgStage`,
> `crg-analysis.json`, `CRG_ENABLED`, `CRG_CACHE_DIR`,
> `CRG_CONTEXT_MAX_BYTES`, and `crg-cache/<repo_id>/crg-<version>`. The audit
> below verifies the **functional** requirements against the landed naming;
> renaming the shipped artifact/env contract was deliberately **not** done
> (`ARTIFACT_NAMES` and deployed env vars are stable contracts per
> `AGENTS.md`). The openspec record was completed to match what was built.

---

## Part A — why nothing persisted across runs

Four independent defects combined into the observed symptom. A1–A5 refer to
the suspect list in the audit task.

### Defect 1 (production, fatal): the CRG package was never in the container image — A3/A4

Evidence:

- `pyproject.toml` declared `code-review-graph>=2.3.7` only under the
  optional `crg` extra (floating range, not a pin).
- `uv.lock` contained **zero** entries for `code-review-graph` — the lock was
  never regenerated after the extra was added, so the package was not
  reproducibly installable anywhere.
- `Dockerfile` installed dependencies with
  `uv export --format requirements-txt --no-dev --no-emit-project`, which
  exports only main dependencies — no extras. The image therefore never
  contained `code_review_graph`.

Consequence: every container run hit the stage's `ImportError` guard and
returned `crg_status: "package_unavailable"`. No graph was ever built, so
there was nothing to persist; the persistent volume and cache path were
irrelevant in production. With `--rm`, anything the stage might have written
outside a volume would have been lost anyway.

Fix:

- `pyproject.toml:31` — pinned exactly: `code-review-graph==2.3.7`.
- `uv.lock` — regenerated; now locks `code-review-graph 2.3.7` and its
  transitive dependencies.
- `Dockerfile:33` — `uv export ... --extra crg` so the image ships the
  package.

### Defect 2 (in-process): cold/warm detection was inverted by eager DB creation — A1

Evidence: `GraphStore.__init__` opens the SQLite file and initialises the
schema immediately (verified against the installed 2.3.7 package source), so
the DB file exists as soon as the store is constructed. The old stage code
constructed `GraphStore(db_path)` **first** and only then tested
`db_path.exists()` — which was therefore always true. The very first run took
the "warm" branch and ran `incremental_update` against an empty graph,
re-parsing only the changed files instead of the repository, and reported
`build_mode: "incremental"` for a cold run.

Fix: `enrich_with_crg.py:86` — `db_existed = db_path.exists()` is captured
**before** `GraphStore(db_path)` is constructed (`enrich_with_crg.py:93`).
Regression test:
`test_first_run_uses_full_build_despite_eager_db_creation` uses a fake store
that replicates the eager file creation and would fail against the old code.

### Defect 3 (warm path correctness): incremental update diffed `HEAD~1` — A5-adjacent

Evidence: the stage called `incremental_update(repo_dir, store)` with no
`changed_files`. The package default is `get_changed_files(repo_root,
base="HEAD~1")`. ReviewForge checkouts are shallow (`git fetch --depth=200`,
deepened only until a merge base exists) and detached at the PR head, so
`HEAD~1` is at best the last commit of the PR — not the PR file set — and at
worst unresolvable. Files changed in earlier PR commits would never be
re-parsed, silently serving a stale graph on warm runs.

Fix: `enrich_with_crg.py:101` — the warm path now passes the pipeline's
changed-file list explicitly:
`incremental_update(repo_dir, store, changed_files=changed_files)`.
Regression test: `test_two_consecutive_runs_cold_then_warm` asserts the warm
call receives exactly `state.files`.

### Defect 4 (cache key): no tool version in the cache path — A5

Evidence: the DB lived at `crg-cache/<repo_id>/crg.db`. A CRG upgrade would
have reused a graph built by an older tool/schema with no cold rebuild.

Fix: `enrich_with_crg.py:194-211` — the path is now
`<cache-root>/<repo_id>/crg-<tool_version>/crg.db`, with the tool version
read from `importlib.metadata`. A version bump costs exactly one cold
rebuild. Regression test:
`test_version_bump_triggers_exactly_one_cold_rebuild`
(full → incremental → bump → full → incremental).

### What was NOT broken (verified, per suspect list)

- **A1 (per-run artifact dir):** the cache root was already
  `cfg.review_artifact_root / "crg-cache"`, not `ctx.artifacts.dir` /
  `run_id`. Confirmed and locked in by test: the DB path is asserted to be
  outside both per-run artifact dirs and to survive their deletion.
- **A2 (repo checkout):** `repo_dir` is used only as the
  analyze/build root argument; the cache never lived under it. Test asserts
  the DB survives `shutil.rmtree(repo_dir)`.
- **A3 (volume mount):** the artifact volume
  (`reviewforge-artifacts:/workspace/artifacts`, or `ARTIFACT_PATH` bind
  mount) was correctly constructed in `ops.py`; `REVIEW_ARTIFACT_ROOT`
  defaults to `/workspace/artifacts` in-container, so the default cache root
  was already on the volume. The problem was that the package was missing
  (Defect 1), not the mount.
- **A4 (env forwarding):** `CRG_ENABLED` travels via `--env-file`. The new
  `CRG_CACHE_DIR` is forwarded explicitly (`ops.py:124`) so the container
  resolves the cache under the dedicated volume.

### User-requested change: dedicated CRG cache volume

Per request, the cache now gets its own attached volume instead of sharing
the artifact tree:

- `ops.py:123-124` — every container run mounts
  `reviewforge-crg-cache:/workspace/crg-cache` (name overridable via
  `REVIEW_CRG_CACHE_VOLUME_NAME`) and exports `CRG_CACHE_DIR=/workspace/crg-cache`.
- `config.py:261` + env resolution at `config.py:410` / `config.py:784` —
  `CRG_CACHE_DIR` overrides the cache root; unset, the default stays
  `<review_artifact_root>/crg-cache` (local runs).
- Tests: `test_crg_cache_volume_and_env_reach_container`,
  `test_crg_cache_volume_name_is_overridable`,
  `test_cache_dir_override_redirects_cache`.

### Persistence acceptance test results

All from `tests/test_stages.py::TestEnrichWithCrgStage` (stubbed CRG package
that replicates eager DB creation):

| Acceptance criterion | Test | Result |
| --- | --- | --- |
| Run 1 cold `build`, run 2 warm `update`, build not called again | `test_two_consecutive_runs_cold_then_warm` | PASS |
| Cache survives deletion of repo checkout and per-run artifact dirs | same test (asserts path outside both, deletes both, DB still exists) | PASS |
| CRG version bump → exactly one cold rebuild | `test_version_bump_triggers_exactly_one_cold_rebuild` | PASS |
| Eager store creation cannot fake "warm" on first run | `test_first_run_uses_full_build_despite_eager_db_creation` | PASS |
| Incremental failure falls back to one full build | `test_falls_back_to_full_build_when_incremental_update_fails` | PASS |

### End-to-end proof (real `code-review-graph` 2.3.7)

Two consecutive `EnrichWithCrgStage` runs against a real temporary git
repository, cache on a separate root (transcript):

```
=== RUN 1 (cold expected)
INFO [review] CRG graph full build: 0 nodes from /tmp/crg-e2e.../repo
INFO [review] CRG enrichment complete: risk_score=0.35, changed_functions=1, test_gaps=0
{"crg_status": "ok", "crg_build_mode": "full", ...}
=== RUN 2 (warm expected)
INFO [review] CRG graph incremental build: 0 nodes from /tmp/crg-e2e.../repo
INFO [review] CRG enrichment complete: risk_score=0.35, changed_functions=1, test_gaps=0
{"crg_status": "ok", "crg_build_mode": "incremental", ...}
=== cache db: /tmp/crg-e2e.../crg-volume/api/crg-2.3.7/crg.db
outside repo checkout: True
outside artifact root: True
survives repo deletion: True
=== run-2 artifact status: ok, build: {'mode': 'incremental', 'duration_ms': 18}
=== E2E OK: cold -> warm across runs
```

Warm update wall time: **18 ms** (well under the 2 s budget; scales with the
number of changed files, not the repo).

### Container-level manual verification (for an operator with docker/podman)

This environment has no container runtime, so the container check is
documented rather than executed here:

1. `python -m reviewforge.ops build` (image now includes `code-review-graph`
   via `uv export --extra crg`; verify with
   `docker run --rm <img> python3 -c "import code_review_graph"`).
2. Set `CRG_ENABLED=1` in `.env`.
3. `python -m reviewforge.ops run --pr-id <ID> --dry-run` twice against the
   same PR.
4. First run's `run.log` shows `CRG graph full build`; the second shows
   `CRG graph incremental build` and the stage duration drops to a few
   seconds at most.
5. Inspect the volume:
   `podman run -it --rm --volume reviewforge-crg-cache:/workspace/crg-cache busybox ls /workspace/crg-cache`
   → `<repo_id>/crg-2.3.7/crg.db` present between runs.

---

## Part B — compliance audit

Legend: **CONFORMS** — verified as planned, no change. **FIXED** — deviated,
fixed in this pass (evidence = post-fix location). **DOCUMENTED** — intentional
mapping decision, no code change.

| # | Item | Verdict | Evidence |
| --- | --- | --- | --- |
| B1 | Stage exists, name, placed between Prepare and Execute in all four engine pipelines | CONFORMS (name DOCUMENTED: `enrich_with_crg`, not `collect_graph_context`) | `pipeline/stages/enrich_with_crg.py:44`; `pipeline/stages/__init__.py:32-74` (all four engine pipeline lists; `POST_ONLY_PIPELINE` runs no engine) |
| B2 | `should_run`: flag AND mode != no_op; flag off = byte-identical | FIXED (explicit `no_op` guard added; byte-identity proven by test) | `enrich_with_crg.py:54-60`; `tests/test_reasoning.py::TestCrgPromptInjection::test_absent_or_failed_analysis_is_byte_identical` |
| B3 | Failure policy: warning, artifact `status: "failed"`, stage returns, never raises | FIXED (failure artifact was not written on build/analysis failure) | `enrich_with_crg.py:271-282`, `_write_failure_document` calls at `:116`, `:152`; tests `test_degrades_gracefully_*` |
| B4 | `analyze_changes` with state files + repo_root; no churn; 500-cap → `degraded` | FIXED (`functions_truncated` was ignored; churn was already off) | `enrich_with_crg.py:144-149`, `:157`; test `test_degraded_status_when_functions_truncated` |
| B5 | Artifact appended additively; canonical shape | FIXED (shape gained `status`/`tool_version`/`build`/`impacted_files`; 13 prior entries untouched) | `artifacts/manager.py:33,67,91,147`; `enrich_with_crg.py:246-268`; test `test_artifact_shape_contract` |
| B6 | Determinism modulo durations | CONFORMS (now enforced by test) | `test_determinism_identical_inputs_identical_artifact` |
| B7 | Enable flag, optional cache dir, max-bytes config, env-resolvable, documented | FIXED (`CRG_CACHE_DIR`, `CRG_CONTEXT_MAX_BYTES` added) | `config.py:256-264,410-411,784-787`; `docs/reference/environment-variables.md`; `tests/test_config.py::TestCrgConfig` |
| B8 | Prompt section on ok\|degraded, before diff, capped, deterministic ordering, subsection caps | FIXED (was uncapped, 10/10/5 caps, no ordering guarantee, any non-failed status passed) | `reasoning/single_pi.py:27-90`, injection at `:140-145`; tests `test_subsection_caps_and_deterministic_ordering`, `test_byte_cap_is_respected`, `test_cfg_byte_cap_flows_into_prefix` |
| B9 | Absent/failed graph → byte-identical instruction | CONFORMS (now enforced by test) | `test_absent_or_failed_analysis_is_byte_identical` |
| B10 | Chunked path: chunk 1 shared prefix only | CONFORMS (session reuse on: prefix is chunk-1-only; with sessions off the whole shared prefix repeats — pre-existing design, not CRG-specific) | `reasoning/single_pi.py:206` (`include_shared_prefix or index == 1`); test `test_chunked_prompt_repeats_graph_context_only_with_shared_prefix` |
| B11 | `prompts/fast-review-system.md` additive section; contract untouched | FIXED (section was missing; added additively — output contract, scope rules, evidence requirements, field names untouched) | `prompts/fast-review-system.md` "Deterministic graph context" section |
| B12 | Python-side only; no MCP/daemon/tools; Pi still `--tools read,grep` scrubbed | CONFORMS | `grep fastmcp/mcp src/` → none; `ai/runner.py:175` `--tools read,grep` |
| B13 | CRG pinned exactly in pyproject AND uv.lock; no other new deps | FIXED (was floating `>=2.3.7`, absent from uv.lock) | `pyproject.toml:31`; `uv.lock` (`code-review-graph 2.3.7`) |
| B14 | Tests for all paths; suite green; coverage gate holds | FIXED (26 new tests; failure branches now covered) | 868 passed / 1 skipped; `--cov-fail-under=97` green; `enrich_with_crg.py` at 100% |
| B15 | openspec record complete and matching the build | FIXED (record had proposal only; the plan's `graph-context` directory name maps to the actual `crg-context-enrichment` change) | `openspec/changes/crg-context-enrichment/{proposal,design,tasks}.md`, `specs/{crg-context-enrichment,single-pi-reasoning}/spec.md`; `openspec validate crg-context-enrichment` → valid |
| B16 | Docs updated from verified behavior; CHANGELOG entries | FIXED (only env-var doc existed) | `docs/architecture/pipeline.md`, `docs/reference/artifacts.md`, `docs/reference/environment-variables.md`, `docs/architecture/ai.md`, `docs/guides/operations.md`; `CHANGELOG.md` Unreleased Added + Fixed |

### Part A suspect checklist

| Suspect | Verdict |
| --- | --- |
| A1 cache under per-run artifact dir | Not the bug for the path itself, but the `exists()` ordering defect (Defect 2) lived here — FIXED |
| A2 cache inside repo checkout | Not present; locked in by survival test |
| A3 volume mount missing / cache outside volume | Mount was correct; the **package** was missing from the image — FIXED (Dockerfile `--extra crg`, lock) |
| A4 env not forwarded | `CRG_ENABLED` was fine via env-file; new `CRG_CACHE_DIR` explicitly forwarded — FIXED |
| A5 run-varying cache key | Key was stable per repo but versionless — FIXED (`crg-<tool_version>`) |

## Final state

- `pytest -q`: **868 passed, 1 skipped** (skip is a pre-existing platform
  guard, unrelated).
- Coverage: `--cov=reviewforge --cov-fail-under=97` green;
  `enrich_with_crg.py` 100%, `single_pi.py` 99%.
- `openspec validate crg-context-enrichment`: valid.
- E2E cold→warm proof with the real package: transcript above.
