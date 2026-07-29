# CRG wave 2 and progressive context disclosure verification
> Module layout note: current CRG implementation lives under `src/reviewforge/pipeline/crg/`; the dated paths below are historical audit references.

**Date:** 2026-07-28  
**Scope:** CRG wave 2 (`GRAPH_API_DIFF`, `GRAPH_FLOWS`, `GRAPH_ARCH`) and progressive `.reviewforge-context` disclosure.  
**Method:** source audit, focused regression tests, local real Git/CRG stage runs, and a container build/run attempt.

## Result

The implementation conforms to the code-level requirements. The requested Docker end-to-end proof is the only incomplete item: Docker is not installed in this execution environment, so no real container transcript can be produced. The local real stage proof passed, including cold base snapshot creation, warm source-graph update, exact base-SHA reuse, staging, independent statuses, and feature timings.

`uv run --extra dev pytest -q tests/test_graph_wave2.py tests/test_context_disclosure.py tests/test_config.py tests/test_ops.py tests/test_reasoning.py tests/test_integration.py tests/test_stages.py` → **426 passed**.

## Requirement audit

Status values: **CONFORMS** means implementation and regression evidence are present; **DEVIATES** means code or evidence does not meet the requirement; **MISSING** means the requested proof could not be run.

### CRG wave 2

| ID | Status | Evidence |
|---|---|---|
| 1.1 | CONFORMS | `src/reviewforge/config.py:266-270,420-425` defines all three flags and the 12288-byte cap, defaulting off. `docs/reference/environment-variables.md:15` documents defaults. `tests/test_config.py:130-142` covers parsing; `tests/test_graph_wave2.py:182-212` verifies the wave-two-off shape and prompt remain phase-one compatible. |
| 1.2 | CONFORMS | `src/reviewforge/pipeline/stages/enrich_with_crg.py:168-224` wraps API, flows, and architecture independently, recording independent durations/statuses. `tests/test_graph_wave2.py:71-139` injects a failure into each feature and verifies the other two remain `ok`. |
| 1.3 | CONFORMS | `src/reviewforge/pipeline/graph_wave2.py:169-210` creates a detached worktree and separate temporary graph database. The base build never uses the warm source graph. `tests/test_graph_wave2.py:156-188` asserts the warm-cache sentinel bytes and mtime are unchanged. |
| 1.4 | CONFORMS | `graph_wave2.py:179-203` caches at `<repo>/base-snapshots/<base-sha>.json`, and `:189-210` registers/removes both temporary paths. `tests/test_graph_wave2.py:171-188` proves the second call does not rebuild, rewrite, or change mtime. |
| 1.5 | CONFORMS | `graph_wave2.py:20-48` computes added/removed/changed nodes and surviving source `CALLS` callers, sorts deterministically, and caps candidates at 50 with a truncation flag. `tests/test_graph_wave2.py:26-37,221-226` covers caller qualification and the capped path. |
| 1.6 | CONFORMS | `openspec/changes/graph-context-wave2/design.md:3-10` records the installed snapshot shape and explicitly states that signatures/source bodies are unavailable; the implementation makes no signature-change claim. |
| 1.7 | CONFORMS | `graph_wave2.py:195-199` calls normal `incremental.full_build` for the detached base graph. `design.md:12-15` records that no flow-skipping option is used and that absent flow APIs degrade only flows. |
| 1.8 | CONFORMS | `graph_wave2.py:65-125` unwraps package flow results, classifies kinds, computes criticality, and sorts by descending score then entry-point name, capped at 15. `tests/test_graph_wave2.py:40-52,228-252` covers ranking, kinds, malformed rows, and absent affected flows. |
| 1.9 | CONFORMS | `graph_wave2.py:138-166` filters hubs/bridges and community inputs to changed nodes plus incoming `CALLS` callers. The package analysis path provides the igraph-optional fallback. `openspec/changes/graph-context-wave2/design.md:26-30` records the fallback; a search of `pyproject.toml` and `uv.lock` found no `igraph`. `tests/test_graph_wave2.py:55-69,254-271` covers changed-node/community behavior and analysis fallback data. |
| 1.10 | CONFORMS | `prompts/fast-review-system.md:89-96` requires architectural impact to be grounded in the architecture section and to say `no significant architectural impact` when absent/empty. |
| 1.11 | CONFORMS | `graph_wave2.py:20-48` keeps the phase-one document fields and adds only `api_surface`, `flows`, and `architecture`. `tests/test_graph_wave2.py:182-212` verifies the wave-two-off artifact key set and excludes all new prompt sections. |
| 1.12 | CONFORMS | `src/reviewforge/reasoning/single_pi.py:202-304,351-381` applies `render_section`/pointers to wave-two and foundation lists; `single_pi.py:565-571` keeps shared preamble/pointers in chunk 1. `tests/test_context_disclosure.py:141-160` covers nested keys, byte caps, and pointer-only-on-truncation. |
| 1.13 | CONFORMS locally | The real cold/warm stage runs recorded `graph_api_diff_ms=40`, `graph_flows_ms=0`, `graph_arch_ms=11` cold and `1/0/0` warm, well below 60 seconds combined. The cold base build is separately called out below and excluded from the warm-path claim. |

### Progressive context disclosure

| ID | Status | Evidence |
|---|---|---|
| 2.1 | CONFORMS | `openspec/changes/progressive-context-disclosure/design.md:3-21` records V1 readable root/cwd, V2 stderr parseability and `unknown`, and V3 session/cwd behavior. The claims cite Dockerfile, runner, and test evidence and explicitly note that no host Pi binary/session exists. |
| 2.2 | CONFORMS | `src/reviewforge/pipeline/context_staging.py:14-22,57-113` copies artifact bytes for metadata, commits, changed files, work items, threads, graph context, writes review state/index, and registers cleanup. `tests/test_context_disclosure.py:85-101,132-138` covers complete copies, idempotent refresh, redaction, and post-CRG refresh. |
| 2.3 | CONFORMS | `src/reviewforge/pipeline/stages/prepare_repository.py:44-51` writes diff/changed files/commits before initial staging and excludes graph context; `context_staging.py:57-74,109-111` refuses repository-owned staging paths and registers cleanup. `tests/test_context_disclosure.py:85-101,119-129` proves no checkout diff/file-list injection, cleanup registration, and pre-existing-path safety. |
| 2.4 | CONFORMS | `src/reviewforge/pipeline/stages/execute_reasoning_engine.py:27-33` passes the prepared checkout to the runner. `src/reviewforge/ai/runner.py:272-280,333-341` passes cwd to review and repair calls. `tests/test_context_disclosure.py:163-186` verifies two sequential calls, stable cwd/session behavior, read counting, and `unknown`. |
| 2.5 | CONFORMS | Foundation and wave-two renderers use the common section/pointer contract in `single_pi.py:202-304,351-381`; pointers contain exact relative path and JSON key and are omitted when untruncated. `context_staging.py:14-22` defines every staged source. `tests/test_context_disclosure.py:141-160` covers the observable pointer rule. |
| 2.6 | CONFORMS | `single_pi.py` receives the staging pointer only through the staged-context path. `tests/test_context_disclosure.py:104-117` proves the checkout-unavailable path emits neither `.reviewforge-context` nor pointers; `prompts.md:20-23` documents the success-only preamble. |
| 2.7 | CONFORMS | `single_pi.py:557-571` includes the prefix only for chunk 1. `tests/test_reasoning.py:590-615` and `tests/test_integration.py:332-345` cover chunk prefix placement and one shared context. |
| 2.8 | CONFORMS | `prompts/fast-review-system.md:88-96`, `prompts/review-system.md:20-23`, and `docs/reference/prompts.md:20-23` add the deterministic-files contract without changing JSON-only output, scope, untrusted-content, or field-name requirements. |
| 2.9 | CONFORMS | `runner.py:77-90,347-351` records parseable reads or `unknown`; `execute_reasoning_engine.py:58-80` places the additive counter in stage details. Existing run-summary serialization persists stage details. The focused suite passed the absence/unparseable-read paths. |

### End-to-end proof

| ID | Status | Evidence |
|---|---|---|
| 3.1 | MISSING for Docker; CONFORMS locally | The required command was attempted with `uv run --no-project python -m reviewforge.ops build --runtime docker --image reviewforge-wave2-audit`; it failed before build because `docker` is not installed (`FileNotFoundError: [Errno 2] No such file or directory: 'docker'`). A real local Git/CRG stage run did complete: cold output logged `CRG graph full build`, `CRG base snapshot built`, all three artifact keys had `status` `ok`; the warm run logged `CRG graph incremental build`, `CRG base snapshot reused`, retained one base snapshot, and recorded `1/0/0` ms feature timings. Staging contained `graph-context.json` and `index.json`. |
| 3.2 | MISSING for requested container artifacts; CONFORMS by regression test | No container baseline/run artifacts could be generated. The wave-two-off regression test passed (`tests/test_graph_wave2.py:182-212`): the graph-context key set equals the phase-one fixture and the instruction contains no wave-two sections. Diff record: `graph-context.json: empty diff`; instruction: `empty diff` (the test assertions are the stored zero-diff result). |
| 3.3 | MISSING for container transcripts; CONFORMS locally | No Docker transcripts exist because Docker is unavailable. The local cold/warm stage transcripts and timings are recorded in §Evidence transcripts below. |

## Evidence transcripts

### Local cold run

```text
INFO [review] CRG graph full build: 3 nodes from <temp>/repo
INFO [review] CRG base snapshot built: <temp>/graph-cache/repo/base-snapshots/<base-sha>.json
INFO [review] CRG enrichment complete: risk_score=0.35, changed_functions=1, test_gaps=1
statuses: api_surface=ok, architecture=ok, flows=ok
details: crg_build_mode=full, graph_api_diff_ms=40, graph_flows_ms=0, graph_arch_ms=11, duration_ms=1519
staging_files: graph-context.json, index.json
base_snapshots: graph-cache/repo/base-snapshots/<base-sha>.json
```

### Local warm run

```text
INFO [review] CRG graph incremental build: 0 nodes from <temp>/repo
INFO [review] CRG base snapshot reused: <temp>/graph-cache/repo/base-snapshots/<base-sha>.json
INFO [review] CRG enrichment complete: risk_score=0.35, changed_functions=1, test_gaps=1
statuses: api_surface=ok, architecture=ok, flows=ok
details: crg_build_mode=incremental, graph_api_diff_ms=1, graph_flows_ms=0, graph_arch_ms=0, duration_ms=27
base_snapshot_count: 1
staging_files: graph-context.json, index.json
```

The cold base build is not included in the warm-path timing requirement. No Pi call was made in this local stage smoke, so a real `context_file_reads` value could not be generated there; runner and stage tests cover parseable, unparseable, and absent reads.

## Fixes applied

- Normalized the installed CRG snapshot edge `set` to deterministic JSON before persistence.
- Restricted API breaking candidates to removed/changed nodes with surviving source `CALLS` edges; added deterministic caps/truncation.
- Corrected flow API unwrapping, affected-flow filtering, criticality fallback, and entry-point classification.
- Isolated API base snapshots in detached worktrees and temporary graph databases; added exact-SHA cache reuse and cleanup evidence.
- Corrected architecture metrics to use changed nodes plus incoming callers and retained the optional networkx fallback.
- Added independent wave-two status/duration handling and fault-injection coverage.
- Made staged `changed-files.json` a complete artifact copy, registered staging cleanup, and refreshed graph context after enrichment.
- Kept deterministic preambles and pointers in chunk 1 only; added skip-path, nested-key, cap, and redaction coverage.
- Added `context_file_reads` propagation and documented the `unknown` fallback.
- Updated architecture, pipeline, operations, prompt, artifact, environment, and troubleshooting documentation plus both active OpenSpec designs/specs/tasks.
- Added the warm-cache sentinel regression and removed duplicate imports in `execute_reasoning_engine.py`.

## Validation limits

- Docker/container build and the two requested `reviewforge review --dry-run` container runs remain unexecuted because the `docker` executable is absent. This is an environment limitation, not a code result.
- No new dependency was added; `igraph` is absent from both `pyproject.toml` and `uv.lock`.
- OpenSpec validation and the full repository suite/coverage gate are run separately after this report is written.
