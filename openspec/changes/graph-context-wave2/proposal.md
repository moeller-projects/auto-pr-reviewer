# Graph context wave 2

## Goal
Add deterministic, Python-side CRG API-surface, flow-criticality, and architecture context to reviews.

## Scope
All three capabilities are independently flag-gated, persisted additively in `graph-context.json`, injected into `single_pi`, and degrade without failing a review. No automatic findings or changes to posting and `multi_stage` flow.
