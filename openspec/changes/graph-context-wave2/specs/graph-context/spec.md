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
