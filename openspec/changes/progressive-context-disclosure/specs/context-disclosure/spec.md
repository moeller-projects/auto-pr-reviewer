# Progressive context disclosure

## ADDED Requirements

### Requirement: Stage complete deterministic context
ReviewForge MUST stage complete available context files under the disposable repository checkout after diff preparation and MUST refresh graph context after graph enrichment.

#### Scenario: Staging succeeds
- WHEN repository preparation has written the context artifacts
- THEN `.reviewforge-context/` contains full source copies, a deterministic index, and no ADO or OpenAI token values

#### Scenario: Repository is unavailable
- WHEN a stage has no readable repository checkout
- THEN staging is skipped, a warning is logged, and no prompt pointer references the absent directory

#### Scenario: Repository-owned staging path
- WHEN the reviewed checkout already contains `.reviewforge-context/`
- THEN staging skips that path without overwriting it and prompt pointers are omitted

#### Scenario: Current graph artifact
- WHEN preparation stages context before CRG enrichment
- THEN it omits `graph-context.json` until the current CRG artifact, including a current failure artifact, is written

### Requirement: Progressive inline summaries
The single-pi instruction MUST retain the curated inline summaries and MUST append an exact staged-file pointer whenever a section omits items or exceeds its byte budget.

#### Scenario: Section is truncated with staging
- WHEN a context section exceeds its item or byte budget and staging succeeded
- THEN the inline section ends with a pointer naming `.reviewforge-context/<file>` and its source key

#### Scenario: Section is untruncated
- WHEN a context section fits its configured budget
- THEN its rendered content remains byte-compatible with the existing section

### Requirement: Explicit readable root
Pi review and JSON-repair subprocesses MUST run with the disposable repository checkout as cwd while preserving the existing session identifier and ModelRunner protocol.

#### Scenario: Reused session
- WHEN two sequential runner calls use the same configured session
- THEN both calls use the same session id and explicit checkout cwd

### Requirement: Context-file prompt contract
The single-pi and multi-stage prompts MUST describe staged files as read-only Python-generated containers, identify inline content and the generated index as deterministic summaries, treat PR-derived contents as untrusted data rather than instructions, and require evidence to mention only files actually read.

#### Scenario: Drill-down
- WHEN inline context points to omitted data
- THEN the model is instructed to read the referenced file before relying on the omitted data

### Requirement: Read audit is additive
The runner MUST expose best-effort per-file reads of `.reviewforge-context/` and MUST report `unknown` when stderr cannot be parsed without failing a review.

#### Scenario: Unparseable diagnostics
- WHEN Pi stderr lacks a recognizable read-tool diagnostic
- THEN stage details contain `context_file_reads: "unknown"` and the review continues
