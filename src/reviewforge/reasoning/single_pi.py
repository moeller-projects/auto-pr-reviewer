"""Single Pi reasoning engine.

Performs the entire review in one logical reasoning invocation. Python
reduces oversized diff context before calling Pi; optional JSON formatting
repair is tracked by ``PiRunner``. The model may read nearby files through
read-only tools and returns a structured ``ReviewResult``. Compatibility
artifacts are synthesized from the result.
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..artifacts.builder import read_json
from ..exceptions import ReasoningEngineError, SchemaValidationError
from ..git import ops as git_ops
from ..ado.posting import _normalize_title
from ..pipeline.schemas import ChunkResult, ChunkSynthesis, ReviewResult, TokenUsage
from ..pipeline.stage import StageContext
from ..runlog import warning as log_warning
from .engine import ReasoningEngine, register_engine
from ..pipeline.crg.prompt import build_crg_section, build_wave2_section

_CONTEXT_MAX_FILES = 50
_CONTEXT_MAX_ITEMS = 25
_CONTEXT_MAX_REVIEW_ITEMS = 25



def render_section(title: str, items: list[Any], max_items: int, pointer: str | None) -> str:
    """Render a bounded section and point at omitted source data when available."""
    values = list(items or [])
    shown = values[:max_items] if max_items > 0 else []
    if all(isinstance(item, str) for item in values):
        body = "\n".join(str(item) for item in shown)
    else:
        body = json.dumps(shown, ensure_ascii=False)
    rendered = f"{title}\n{body}" if body else title
    omitted = max(0, len(values) - len(shown))
    if omitted and pointer:
        rendered += f"\n…and {omitted} more — full data: {pointer}"
    return rendered


def _byte_cap_with_pointer(text: str, max_bytes: int, pointer: str | None) -> str:
    if max_bytes <= 0 or len(text.encode("utf-8")) <= max_bytes:
        return "" if max_bytes <= 0 else text
    if not pointer:
        return _utf8_prefix(text, max_bytes)
    marker = f"…and more — full data: {pointer}"
    budget = max_bytes - len(marker.encode("utf-8")) - 1
    if budget <= 0:
        return _utf8_prefix(text, max_bytes)
    return _utf8_prefix(text, budget).rstrip() + "\n" + marker





def _runner_usage(runner: Any) -> dict[str, int]:
    usage = getattr(runner, "token_usage", None)
    if isinstance(usage, dict):
        return {k: int(usage.get(k, 0) or 0) for k in ("in", "out", "total")}
    usage = getattr(runner, "last_tokens", {})
    if isinstance(usage, dict):
        return {k: int(usage.get(k, 0) or 0) for k in ("in", "out", "total")}
    return {}


def _runner_count(runner: Any, name: str) -> int:
    value = getattr(runner, name, 0)
    return value if isinstance(value, int) else 0


def _context_pointer(context_dir: Any, filename: str, key: str) -> str | None:
    return f".reviewforge-context/{filename} (key: {key})" if context_dir else None


def _trim_review_state(review_context: Any, context_dir: Any) -> Any:
    if not isinstance(review_context, dict):
        return review_context
    inline = dict(review_context)
    for key in ("previousComments", "activeComments", "resolvedComments", "changedCommits", "changedFiles"):
        values = inline.get(key)
        if isinstance(values, list) and len(values) > _CONTEXT_MAX_REVIEW_ITEMS:
            inline[key] = values[:_CONTEXT_MAX_REVIEW_ITEMS]
    return inline


def _review_state_pointers(review_context: Any, context_dir: Any) -> list[str]:
    if not isinstance(review_context, dict) or not context_dir:
        return []
    return [
        f"…and {len(review_context[key]) - _CONTEXT_MAX_REVIEW_ITEMS} more — full data: .reviewforge-context/review-state.json (key: {key})"
        for key in ("previousComments", "activeComments", "resolvedComments", "changedCommits", "changedFiles")
        if isinstance(review_context.get(key), list) and len(review_context[key]) > _CONTEXT_MAX_REVIEW_ITEMS
    ]


def _feedback_section(feedback: Any, context_dir: Any) -> list[str]:
    if not feedback:
        return []
    section = (
        render_section("\nPrevious review feedback:", feedback, _CONTEXT_MAX_ITEMS, _context_pointer(context_dir, "review-state.json", "previousFeedback"))
        if len(feedback) > _CONTEXT_MAX_ITEMS
        else "\nPrevious review feedback:\n" + json.dumps(feedback, ensure_ascii=False, sort_keys=True)
    )
    return [section, "\nDo not re-raise dismissed findings unless the implicated code changed in THIS diff. Treat fixed findings as addressed, but flag them when reintroduced and set regression=true."]


def _prefix_review_state(ctx: StageContext, context_dir: Any) -> list[str]:
    review_context = ctx.extras.get("review_context")
    if not review_context:
        return []
    inline = _trim_review_state(review_context, context_dir)
    pointers = _review_state_pointers(review_context, context_dir)
    parts = ["\nDeterministic review state:\n" + json.dumps(inline, ensure_ascii=False, sort_keys=True) + ("\n" + "\n".join(pointers) if pointers else "")]
    feedback = review_context.get("previousFeedback", []) if isinstance(review_context, dict) else []
    parts.extend(_feedback_section(feedback, context_dir))
    return parts


def _prefix_graph_context(ctx: StageContext, context_dir: Any) -> list[str]:
    parts = []
    if crg := ctx.extras.get("crg_analysis"):
        section = build_crg_section(crg, getattr(ctx.cfg, "crg_context_max_bytes", 8192), context_dir, render_section, _byte_cap_with_pointer)
        if section:
            parts.append("\nDeterministic graph context (Tree-sitter code-review graph):\n" + section)
    if graph := ctx.extras.get("graph_context") and any(getattr(ctx.cfg, name, False) for name in ("graph_api_diff", "graph_flows", "graph_arch")):
        section = build_wave2_section(ctx.extras["graph_context"], getattr(ctx.cfg, "graph_context_max_bytes", 12288), context_dir, render_section, _byte_cap_with_pointer)
        if section:
            parts.append("\n" + section)
    return parts

def _staging_section(index: Any, context_dir: Any) -> str:
    if not isinstance(index, dict) or not context_dir:
        return ""
    names = "\n".join(
        f"  - {name}: {info.get('description', '')}"
        for name, info in sorted(index.items())
        if isinstance(info, dict)
    )
    return "\nDeterministic context files:\n" + names + "\nInline sections are authoritative summaries; read the referenced files for complete data."


def _changed_files_section(ctx: StageContext, context_dir: Any) -> str:
    changed = list(getattr(ctx.state, "files", []) if ctx.state is not None else [])
    if not changed and getattr(ctx, "files_text", ""):
        changed = [line for line in ctx.files_text.splitlines() if line]
    if changed and len(changed) > _CONTEXT_MAX_FILES:
        return render_section("\nChanged files:", changed, _CONTEXT_MAX_FILES, _context_pointer(context_dir, "changed-files.json", "all entries"))
    return "\nChanged files:\n" + (getattr(ctx, "files_text", "") or "\n".join(changed) or "(no changed files)")


def _context_item_sections(ctx: StageContext, context_dir: Any) -> list[str]:
    return [
        render_section(f"\n{label}:", value if isinstance(value, list) else [value], _CONTEXT_MAX_ITEMS, _context_pointer(context_dir, filename, "all entries"))
        for label, value, filename in (
            ("Linked work items", ctx.extras.get("wi_context", []), "work-items.json"),
            ("Existing PR comments", ctx.extras.get("thread_context", []), "threads.json"),
        )
        if value
    ]

def _build_single_pi_prefix(ctx: StageContext) -> str:
    """Build the shared non-diff prefix for single-pi prompts."""
    metadata = ctx.metadata or (read_json(ctx.artifacts.metadata) if ctx.artifacts.metadata.exists() else {})
    context_dir = ctx.extras.get("context_staging_dir")
    parts = [
        f"Single-call reasoning review for Azure DevOps PR #{ctx.cfg.pr_id}.",
        "Return only the rich ReviewResult JSON object defined in the system prompt.",
    ]
    if section := _staging_section(ctx.extras.get("context_staging_index"), context_dir):
        parts.append(section)
    if metadata:
        parts += ["\nRepository/project metadata:", json.dumps(metadata, ensure_ascii=False)]
    parts.append(_changed_files_section(ctx, context_dir))
    if commits := _all_commit_lines(ctx):
        parts.append(render_section("\nCommits in this PR:", commits, getattr(ctx.cfg, "commit_context_max", 50), _context_pointer(context_dir, "commits.txt", "commits")))
    parts.extend(_context_item_sections(ctx, context_dir))
    parts.extend(_prefix_review_state(ctx, context_dir))
    parts.extend(_prefix_graph_context(ctx, context_dir))
    return "\n".join(parts)


def _utf8_prefix(text: str, max_bytes: int) -> str:
    """Return the longest UTF-8-safe prefix fitting ``max_bytes``."""
    return text.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")

def _all_commit_lines(ctx: StageContext) -> list[str]:
    if ctx.artifacts.commits.exists():
        text = ctx.artifacts.commits.read_text(encoding="utf-8")
    elif ctx.state is not None and getattr(ctx.state, "repo_dir", None):
        text = git_ops.run_git(ctx.state.repo_dir, "log", "--oneline", ctx.state.range_spec)
    else:
        text = ""
    return text.splitlines()


def _diff_chunks(diff_text: str, max_bytes: int) -> list[str]:
    """Partition a unified diff at file boundaries in stable source order."""
    if len(diff_text.encode("utf-8")) <= max_bytes:
        return [diff_text]
    sections = [f"diff --git {part}" for part in diff_text.split("diff --git ") if part]
    chunks: list[str] = []
    current = ""
    for section in sections:
        if current and len((current + section).encode("utf-8")) > max_bytes:
            chunks.append(current)
            current = ""
        current += section
    if current:
        chunks.append(current)
    return chunks


def _build_single_pi_instruction(ctx: StageContext) -> str:
    """Build the user message for a non-chunked reasoning review."""
    prefix = _build_single_pi_prefix(ctx)
    diff_text = getattr(ctx.state, "diff_text", "") or (
        ctx.artifacts.diff.read_text(encoding="utf-8") if ctx.artifacts.diff.exists() else ""
    )
    parts = [prefix]
    if diff_text:
        parts += ["\nUnified diff:\n", diff_text]
    return "\n".join(parts) + "\nReturn only the ReviewResult JSON object defined in the system prompt.\n"


def _build_chunk_instruction(
    ctx: StageContext,
    chunk: str,
    index: int,
    total: int,
    *,
    include_shared_prefix: bool,
) -> str:
    prefix = _build_single_pi_prefix(ctx) if include_shared_prefix or index == 1 else ""
    body = (
        f"Review chunk {index}/{total} of the same PR diff. "
        "Return only a JSON object with findings and uncertainties; do not summarize the PR.\n"
        f"Unified diff chunk:\n{chunk}"
    )
    return f"{prefix}\n\n{body}" if prefix else body


def _synthesis_lines(
    findings: list[dict[str, Any]], uncertainties: list[dict[str, Any]]
) -> list[str]:
    lines = []
    for finding in findings:
        location = finding.get("file") or "general"
        if finding.get("line"):
            location = f"{location}:{finding['line']}"
        lines.append(f"- [{finding.get('severity', 'minor')}] {finding.get('title', '')} ({location})")
    lines.append("- none" if not findings else "")
    lines.append("Merged uncertainties across all chunks:")
    lines.extend(f"- {item.get('topic', '')}" for item in uncertainties)
    if not uncertainties:
        lines.append("- none")
    return lines
def _build_synthesis_instruction(
    chunk_count: int,
    findings: list[dict[str, Any]],
    uncertainties: list[dict[str, Any]],
) -> str:
    """Build the whole-PR synthesis request; no diff is re-sent."""
    lines = [
        f"You reviewed this pull request in {chunk_count} coherent diff chunks.",
        "Base the summaries on your prior chunk analyses in this session and the merged results below.",
        "",
        "Merged findings across all chunks:",
    ]
    lines.extend(_synthesis_lines(findings, uncertainties))
    lines.extend(["", "Return only the chunk-synthesis JSON object defined in the system prompt."])
    return "\n".join(lines)


def _select_chunks(ctx: StageContext, diff_text: str) -> list[str]:
    cfg = ctx.cfg
    if cfg.disable_chunk_review:
        log_warning("DISABLE_CHUNK_REVIEW enabled; forcing single-pass reasoning")
        return [diff_text]
    if len(diff_text.encode("utf-8")) <= cfg.chunk_trigger_diff_bytes:
        return [diff_text]
    log_warning(
        f"diff exceeds CHUNK_TRIGGER_DIFF_BYTES ({cfg.chunk_trigger_diff_bytes}); "
        "using chunked single-pi reasoning"
    )
    return _diff_chunks(diff_text, cfg.max_diff_bytes)


def _single_pass(ctx: StageContext, cfg: Any) -> ReviewResult:
    output_path = ctx.artifacts.raw_dir / "fast-review.json"
    ctx.pi.run_json(cfg.fast_review_prompt_path, _build_single_pi_instruction(ctx), output_path, "single-pi reasoning")
    raw = read_json(output_path)
    if raw is None:
        raise ReasoningEngineError("single-pi reasoning produced no JSON", details={"output_path": str(output_path)})
    try:
        return ReviewResult.model_validate(raw)
    except Exception as exc:
        raise SchemaValidationError("single-pi response does not match ReviewResult schema", details={"error": str(exc), "output_path": str(output_path)}) from exc


def _merge_chunk(
    partial: ChunkResult,
    seen: set[tuple[str | None, int | None, str]],
    findings: list[dict[str, Any]],
    uncertainties: list[dict[str, Any]],
) -> None:
    for finding in partial.findings:
        key = (finding.file, finding.line, _normalize_title(finding.title))
        if key not in seen:
            seen.add(key)
            findings.append(finding.model_dump(by_alias=True))
    uncertainties.extend(item.model_dump(by_alias=True) for item in partial.uncertainties)


def _chunked_pass(
    engine: Any, ctx: StageContext, cfg: Any, chunks: list[str]
) -> tuple[ReviewResult, list[TokenUsage]]:
    findings, uncertainties, usage = [], [], []
    seen: set[tuple[str | None, int | None, str]] = set()
    previous_tokens = _runner_usage(ctx.pi)
    repeat_prefix = not cfg.pi_session_enabled or cfg.pi_session_clear
    for index, chunk in enumerate(chunks, 1):
        output_path = ctx.artifacts.raw_dir / f"fast-review-{index}.json"
        ctx.pi.run_json(
            cfg.fast_review_prompt_path,
            _build_chunk_instruction(ctx, chunk, index, len(chunks), include_shared_prefix=repeat_prefix),
            output_path,
            f"single-pi chunk {index}/{len(chunks)}",
        )
        try:
            partial = ChunkResult.model_validate(read_json(output_path))
        except Exception as exc:
            raise SchemaValidationError(
                "single-pi chunk response does not match ChunkResult schema",
                details={"error": str(exc), "output_path": str(output_path)},
            ) from exc
        current = _runner_usage(ctx.pi)
        usage.append(
            TokenUsage(
                input=max(0, current.get("in", 0) - previous_tokens.get("in", 0)),
                output=max(0, current.get("out", 0) - previous_tokens.get("out", 0)),
                total=max(0, current.get("total", 0) - previous_tokens.get("total", 0)),
            )
        )
        previous_tokens = current
        _merge_chunk(partial, seen, findings, uncertainties)
    synthesis = engine._synthesize(ctx, len(chunks), findings, uncertainties)
    payload = (
        {
            "review_summary": synthesis.review_summary.model_dump(),
            "verification_summary": synthesis.verification_summary.model_dump(),
            "pr_summary": synthesis.pr_summary.model_dump(),
            "good_practices": [gp.model_dump() for gp in synthesis.good_practices],
        }
        if synthesis is not None
        else {
            "review_summary": {"summary": f"Reviewed {len(chunks)} coherent diff chunks."},
            "verification_summary": {"summary": "Reviewed each deterministic unified-diff chunk.", "approach": "chunked diff review"},
            "pr_summary": {"implementation_summary": f"Reviewed {len(chunks)} unified-diff chunks."},
        }
    )
    if synthesis is None:
        ctx.extras["_synthesis_fallback"] = True
    payload.update(findings=findings, uncertainties=uncertainties)
    return ReviewResult.model_validate(payload), usage


def _update_metrics(
    result: ReviewResult, ctx: StageContext, started_at: float,
    finished_at: float, reasoning_duration_ms: int, chunks: list[str], chunk_usage: list[TokenUsage],
) -> ReviewResult:
    tokens = _runner_usage(ctx.pi)
    result.metrics = result.metrics.model_copy(update={
        "piInputTokens": tokens.get("in", 0), "piOutputTokens": tokens.get("out", 0),
        "piTotalTokens": tokens.get("total", 0), "invocationCount": _runner_count(ctx.pi, "invocation_count"),
        "repairInvocationCount": _runner_count(ctx.pi, "repair_invocation_count"),
        "wallClockDurationMs": int((finished_at - started_at) * 1000),
        "reasoningDurationMs": reasoning_duration_ms, "projectionDurationMs": 0,
        "validationDurationMs": 0, "changedFilesReviewed": len(getattr(ctx.state, "files", [])),
        "chunkCount": len(chunks), "chunkTokenUsage": chunk_usage,
    })
    return result
class SinglePiReasoningEngine(ReasoningEngine):
    """One Pi call that returns a full ``ReviewResult``."""

    def __init__(self, cfg: Any | None = None) -> None:
        self._cfg = cfg

    @property
    def name(self) -> str:
        return "single_pi"

    def execute(self, ctx: StageContext) -> ReviewResult:
        cfg = ctx.cfg
        diff_text = getattr(ctx.state, "diff_text", "") or (
            ctx.artifacts.diff.read_text(encoding="utf-8") if ctx.artifacts.diff.exists() else ""
        )
        chunks = _select_chunks(ctx, diff_text)
        started_at = time.time()
        reasoning_started = time.perf_counter()
        if len(chunks) == 1:
            result = _single_pass(ctx, cfg)
            chunk_usage: list[TokenUsage] = []
        else:
            result, chunk_usage = _chunked_pass(self, ctx, cfg, chunks)
        reasoning_duration_ms = int((time.perf_counter() - reasoning_started) * 1000)
        tokens = _runner_usage(ctx.pi)
        ctx.last_token_usage = tokens
        finished_at = time.time()
        result = self._enrich_metadata(result, cfg, started_at, finished_at, tokens)
        return _update_metrics(result, ctx, started_at, finished_at, reasoning_duration_ms, chunks, chunk_usage)

    def _synthesize(
        self,
        ctx: StageContext,
        chunk_count: int,
        findings: list[dict[str, Any]],
        uncertainties: list[dict[str, Any]],
    ) -> ChunkSynthesis | None:
        """Ask Pi for whole-PR summaries; ``None`` means use boilerplate."""
        output_path = ctx.artifacts.raw_dir / "chunk-synthesis.json"
        try:
            ctx.pi.run_json(
                ctx.cfg.chunk_synthesis_prompt_path,
                _build_synthesis_instruction(chunk_count, findings, uncertainties),
                output_path,
                "single-pi synthesis",
            )
            return ChunkSynthesis.model_validate(read_json(output_path))
        except Exception as exc:  # noqa: BLE001 - summaries must never fail a review
            log_warning(
                f"chunk synthesis unavailable ({type(exc).__name__}: {exc}); "
                "falling back to deterministic summaries"
            )
            return None

    def _enrich_metadata(
        self,
        result: ReviewResult,
        cfg: Any,
        started_at: float,
        finished_at: float,
        tokens: dict[str, int] | None,
    ) -> ReviewResult:
        """Fill in run metadata that the model cannot know."""
        from ..pipeline.schemas import ModelMetadata, ReviewMetadata, TokenUsage

        tokens = tokens or {}

        result.metadata = ReviewMetadata(
            started_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started_at)),
            finished_at=time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(finished_at)),
            duration_ms=int((finished_at - started_at) * 1000),
            model=ModelMetadata(
                model=cfg.pi_model,
                reasoning_engine=self.name,
            ),
            tokens=TokenUsage(
                input=int(tokens.get("in", 0) or 0),
                output=int(tokens.get("out", 0) or 0),
                total=int(tokens.get("total", 0) or 0),
            ),
        )
        return result



register_engine(SinglePiReasoningEngine().name, SinglePiReasoningEngine)
