# Design

## Verified runtime facts

- **V1 readable root:** `Dockerfile` sets `WORKDIR /workspace`, and the current `PiCliRunner` passed no `cwd`, so subprocesses inherited `/workspace`. `prepare_repo` creates the disposable checkout below `CLONE_ROOT` (default `/workspace/repo`). The runner enables only `read,grep` with `--no-context-files`; the repository is readable because Pi starts from the workspace and the system prompt directs it to inspect checkout files. Pi is not installed in the host development environment, so Pi's internal path sandbox was not black-box exercised. This change makes the choice deliberate by setting Pi's cwd to the actual checkout before engine calls.
- **V2 stderr audit:** The repository exposes Pi stderr as decoded line-oriented diagnostics and currently parses only token usage. No installed Pi binary or stable tool-call trace format was available to verify a canonical read-event grammar. The audit therefore recognizes lines containing `read` and `.reviewforge-context/<file>` and returns `unknown` when stderr exposes no parseable read diagnostic. Unknown is observability data, not a review failure.
- **V3 session/cwd behavior:** Session identity is explicit `--session-id <id>` and is computed independently of cwd. A two-call mocked runner test verifies sequential `run_json` calls retain the same session id while both calls receive the explicit checkout cwd. No real Pi session was available in the host environment.

## Staging

`stage_context_files(ctx)` copies existing artifact bytes into `<repo_dir>/.reviewforge-context/`, redacting values from the runlog secret list plus the configured ADO token. It writes a deterministic `index.json` with descriptions and JSON top-level keys. `review-state.json` is the one exception to the artifact-copy rule: the current repository has no declared review-state artifact, so the existing `ctx.extras["review_context"]` payload is serialized directly into the disposable staging directory. Preparation stages the initial set after diff, changed files, and commits are written; CRG refreshes the graph copy after its artifact write. Existing `repo_dir` cleanup removes the staging directory.

Staging refuses to touch a pre-existing `.reviewforge-context` directory in the reviewed checkout, so repository-owned files cannot be overwritten. Preparation excludes `graph-context.json`; the graph file is staged only after the current CRG artifact is written, including current failure artifacts. This prevents stale graph data from surviving skipped or failed enrichment.

## Rendering

`render_section` owns top-N list rendering and emits a pointer only when staging succeeded and items were omitted. Existing formatting is retained when a section fits. Byte caps reserve a final pointer line when staged data is truncated; without staging, summaries remain bounded and omit both markers and pointers. Chunk 1 owns the shared preamble and pointers; later chunk instructions remain diff-only unless the existing session policy repeats the shared prefix.

## Observability

`PiCliRunner` keeps an additive `context_file_reads` dict or `"unknown"`, aggregates it across review and repair calls, and `ExecuteReasoningEngineStage` places it in stage details. The existing run-summary serializer persists those details without changing artifact names or model contracts.
