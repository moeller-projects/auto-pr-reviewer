## MODIFIED Requirements

### Requirement: Single-pi prompt prefix includes deterministic graph context
The single-pi prompt prefix MUST append a "Deterministic graph context" section before the diff when `ctx.extras["crg_analysis"]` has status `ok` or `degraded`. The section MUST be deterministically ordered (risk descending, path ascending), capped to 5 review priorities, 15 changed functions, 30 impacted files, and 15 test gaps, and truncated UTF-8-safely at `crg_context_max_bytes` (`CRG_CONTEXT_MAX_BYTES`, default 8192).

#### Scenario: Successful analysis
- **WHEN** a CRG document with status `ok` is present
- **THEN** the instruction MUST contain the graph-context section before the unified diff

#### Scenario: Absent or failed analysis
- **WHEN** no CRG document is present or its status is not `ok`/`degraded`
- **THEN** the instruction MUST be byte-identical to the same context without CRG data

#### Scenario: Chunked review
- **WHEN** the diff is reviewed in multiple chunks with Pi session reuse enabled
- **THEN** the graph-context section MUST appear in chunk 1's shared prefix only and MUST NOT be repeated per chunk
