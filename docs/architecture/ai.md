# AI interaction

**Purpose:** describe how Pi is invoked safely. **Audience:** maintainers changing prompts or model execution. **Mode:** explanation.

`ai.model_runner.ModelRunner` is the model execution contract used by engines and stages. It exposes JSON execution plus token and invocation counters; every backend must scrub ADO credentials from child environments and restrict model-side tools to read-only operations.

`create_model_runner(Config)` currently supports only `MODEL_BACKEND=pi`, creating `ai.runner.PiCliRunner`. `PiRunner` remains a deprecated compatibility alias for one release. Pi composes prompt files through `ai.prompts`, records token usage from stderr, and repairs invalid JSON in the same session with a JSON-only instruction.

Session reuse is enabled by default for the Pi backend. The default identifier is `pr-<pr_id>-review`; `--pi-session-id` overrides it, `--no-pi-session` disables reuse, and `--pi-session-clear` starts fresh state under the same id. The session behavior matters most to the multi-stage engine and chunked calls.

Prompts are files, not embedded Python templates. Runtime augmentation adds language and standards where applicable. See [prompt reference](../reference/prompts.md) and [prompt development](../guides/prompt-development.md).

When `CRG_ENABLED` is set, `EnrichWithCrgStage` prepends a deterministic "Deterministic graph context" section to the single-pi user message (before the diff). The section is produced Python-side by the `code-review-graph` package — no model call, no MCP server, no extra Pi tools — and is capped, ordered, and omitted entirely when analysis fails, so failed runs produce byte-identical prompts to disabled runs.

The model response is parsed and validated against Pydantic schemas. Invalid output is not silently coerced into a valid finding; schema errors are surfaced through the domain error path.
