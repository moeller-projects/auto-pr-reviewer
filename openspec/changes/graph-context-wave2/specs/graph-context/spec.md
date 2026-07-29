# Graph context wave two

## ADDED Requirements

### Requirement: Independent deterministic graph features
The graph enrichment stage MUST expose API-surface, flow-criticality, and architecture context behind independent flags and MUST continue the review when any feature fails.

#### Scenario: One feature fails
- WHEN an enabled graph feature raises
- THEN its artifact section is marked degraded and the review continues with other sections

### Requirement: Additive graph context
The stage MUST write `graph-context.json` with additive `api_surface`, `flows`, and `architecture` keys when their flags are enabled.

#### Scenario: Feature succeeds
- WHEN a flagged feature completes
- THEN its section contains deterministic, sorted, capped output and a per-feature status

### Requirement: Base snapshot isolation
API-surface analysis MUST build a base snapshot in a disposable git worktree
and temporary graph database, cache it by base SHA under the graph-cache
repository namespace, and MUST NOT modify the warm source graph cache.

#### Scenario: Cached base reuse
- WHEN the same base SHA is analyzed twice
- THEN the second analysis reads `base-snapshots/<base-sha>.json` without a base graph build

### Requirement: Snapshot-supported detections
API-surface analysis MUST report only node and edge changes supported by
`take_snapshot` data and MUST require surviving incoming source `CALLS` edges
for breaking candidates; it MUST NOT claim signature-change detection.

#### Scenario: No surviving caller
- WHEN a base node is removed but no source `CALLS` edge targets it
- THEN the node is absent from `breaking_candidates`
