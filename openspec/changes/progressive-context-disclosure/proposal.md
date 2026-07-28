# Progressive context disclosure

## Goal
Replace silent inline context truncation with progressive disclosure: keep curated summaries in the Pi instruction, stage complete redacted context inside the readable checkout, and emit exact pointers whenever inline data is truncated.

## Scope
All `single_pi` context sections and the legacy review prompt contract use the staged files. Pi review and repair subprocesses run with the disposable checkout as cwd. Read-audit counts are additive observability only. No changes to the model-runner protocol, tool lockdown, posting path, artifact names, or review-result schema.
