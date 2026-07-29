# Design

## Verified runtime facts

- **V1 readable root:** `Dockerfile:47-49` sets `/workspace` as the runtime
  workdir. `PrepareRepositoryStage` creates the disposable checkout and
  `ExecuteReasoningEngineStage:28-31` calls `PiCliRunner.set_working_dir` with
  that checkout. `runner.py:209-213` locks Pi to `read,grep`; the staged
  directory is therefore readable through the explicit checkout cwd. The host
  has no installed `pi` binary, so the cwd claim is verified by the
  subprocess test, not a host Pi run.
- **V2 stderr audit:** `runner.py:77-90` parses lines containing `read` and
  `.reviewforge-context/<file>`. No stable Pi tool-event grammar is available
  in this environment; `_parse_context_file_reads` returns `unknown` when
  stderr has no parseable diagnostic. `tests/test_context_disclosure.py`
  exercises both parseable and unparseable stderr.
- **V3 session/cwd behavior:** `runner.py:202-218` emits one explicit
  `--session-id` per configured session and `runner.py:272-280` /
  `333-341` passes the same cwd to review and repair calls. The sequential
  runner test records two calls and asserts identical session flags and cwd.
  No real Pi session is available in the host environment.

## Staging

`stage_context_files(ctx)` copies existing artifact bytes into `<repo_dir>/.reviewforge-context/`, redacting values from the runlog secret list plus the configured ADO token. It writes a deterministic `index.json` with descriptions and JSON top-level keys. `review-state.json` is the one exception to the artifact-copy rule: the current repository has no declared review-state artifact, so the existing `ctx.extras["review_context"]` payload is serialized directly into the disposable staging directory. Preparation stages the initial set after diff, changed files, and commits are written; CRG refreshes the graph copy after its artifact write. Existing `repo_dir` cleanup removes the staging directory.

Staging refuses to touch a pre-existing `.reviewforge-context` directory in the reviewed checkout, so repository-owned files cannot be overwritten. Preparation excludes `graph-context.json`; the graph file is staged only after the current CRG artifact is written, including current failure artifacts. This prevents stale graph data from surviving skipped or failed enrichment.

## Rendering

`render_section` owns top-N list rendering and emits a pointer only when staging succeeded and items were omitted. Existing formatting is retained when a section fits. Byte caps reserve a final pointer line when staged data is truncated; without staging, summaries remain bounded and omit both markers and pointers. Chunk 1 owns the shared preamble and pointers; later chunk instructions remain diff-only unless the existing session policy repeats the shared prefix.

## Observability

`PiCliRunner` keeps an additive `context_file_reads` dict or `"unknown"`, aggregates it across review and repair calls, and `ExecuteReasoningEngineStage` places it in stage details. The existing run-summary serializer persists those details without changing artifact names or model contracts.
