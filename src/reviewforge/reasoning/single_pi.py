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
from pathlib import Path
from typing import Any

from ..artifacts.builder import read_json
from ..exceptions import ReasoningEngineError, SchemaValidationError
from ..git import ops as git_ops
from ..ado.posting import _normalize_title
from ..pipeline.schemas import ChunkResult, ChunkSynthesis, ReviewResult, TokenUsage
from ..pipeline.stage import StageContext
from ..runlog import warning as log_warning
from .engine import ReasoningEngine, register_engine


#: Subsection caps for the deterministic graph-context prompt block. Keep
#: the block small and bounded; the model can read files for anything else.
_CRG_MAX_PRIORITIES = 5
_CRG_MAX_FUNCTIONS = 15
_CRG_MAX_PATHS = 30
_CRG_MAX_TEST_GAPS = 15

_CONTEXT_MAX_FILES = 50
_CONTEXT_MAX_ITEMS = 25
_CONTEXT_MAX_REVIEW_ITEMS = 25

def _crg_entries(value: Any) -> list[dict[str, Any]]:
    """Return only dict entries; malformed CRG items are dropped."""
    return [item for item in value or [] if isinstance(item, dict)]


def _crg_risk(item: dict[str, Any]) -> float:
    """Best-effort numeric risk; malformed scores sort as zero."""
    try:
        return float(item.get("risk_score", 0) or 0)
    except (TypeError, ValueError):
        return 0.0



def _crg_entry_sort_key(item: dict[str, Any]) -> tuple:
    """Deterministic ordering: risk descending, then path/name ascending."""
    name = item.get("qualified_name") or item.get("name") or ""
    file = item.get("file") or item.get("file_path") or ""
    return (-_crg_risk(item), str(file), str(name))


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


def _format_crg_context(
    analysis: dict[str, Any],
    max_bytes: int,
    context_dir: Path | None = None,
) -> str:
    """Format the complete CRG analysis as a bounded progressive summary."""
    if not isinstance(analysis, dict) or not analysis or max_bytes <= 0:
        return ""
    status = analysis.get("status") or analysis.get("crg_status")
    if status not in {"ok", "degraded"}:
        return ""
    pointer = (
        ".reviewforge-context/graph-context.json (key: {key})"
        if context_dir
        else None
    )
    lines: list[str] = []
    summary = analysis.get("summary", "")
    if summary:
        lines.append(str(summary).strip())
    if status == "degraded":
        lines.append("Note: analysis was truncated at the tool's function cap; results are partial.")
    try:
        lines.append(f"Overall risk score: {float(analysis['risk_score']):.2f}")
    except (KeyError, TypeError, ValueError):
        pass

    priorities = sorted(_crg_entries(analysis.get("review_priorities")), key=_crg_entry_sort_key)
    if priorities:
        lines.extend(
            render_section(
                "Review priorities (highest risk first):",
                [
                    f"  - {item.get('qualified_name') or item.get('name', '?')} "
                    f"(risk={_crg_risk(item):.2f})"
                    for item in priorities
                ],
                _CRG_MAX_PRIORITIES,
                pointer.format(key="review_priorities") if pointer else None,
            ).splitlines()
        )
    functions = sorted(_crg_entries(analysis.get("changed_functions")), key=_crg_entry_sort_key)
    if functions:
        lines.extend(
            render_section(
                "Changed functions (highest risk first):",
                [
                    f"  - {item.get('qualified_name') or item.get('name', '?')} "
                    f"({item.get('file') or item.get('file_path') or '?'}, "
                    f"risk={_crg_risk(item):.2f})"
                    for item in functions
                ],
                _CRG_MAX_FUNCTIONS,
                pointer.format(key="changed_functions") if pointer else None,
            ).splitlines()
        )
    impacted = sorted(str(path) for path in (analysis.get("impacted_files") or []))
    if impacted:
        lines.extend(
            render_section(
                "Impacted files:",
                [f"  - {path}" for path in impacted],
                _CRG_MAX_PATHS,
                pointer.format(key="impacted_files") if pointer else None,
            ).splitlines()
        )
    test_gaps = sorted(_crg_entries(analysis.get("test_gaps")), key=_crg_entry_sort_key)
    if test_gaps:
        lines.extend(
            render_section(
                "Functions without test coverage:",
                [
                    f"  - {item.get('qualified_name') or item.get('name', '?')}"
                    for item in test_gaps
                ],
                _CRG_MAX_TEST_GAPS,
                pointer.format(key="test_gaps") if pointer else None,
            ).splitlines()
        )
    affected_flows = [str(flow) for flow in (analysis.get("affected_flows") or [])]
    if affected_flows:
        if len(affected_flows) <= _CRG_MAX_PRIORITIES:
            lines.append(f"Affected flows: {', '.join(affected_flows)}")
        else:
            lines.extend(
                render_section(
                    "Affected flows:",
                    [f"  - {flow}" for flow in affected_flows],
                    _CRG_MAX_PRIORITIES,
                    pointer.format(key="affected_flows") if pointer else None,
                ).splitlines()
            )
    return _byte_cap_with_pointer(
        "\n".join(lines),
        max_bytes,
        pointer.format(key="full") if pointer else None,
    )

def _format_wave2_context(
    context: dict[str, Any],
    max_bytes: int,
    context_dir: Path | None = None,
) -> str:
    """Format wave-two graph context into progressive-disclosure sections."""
    if not isinstance(context, dict) or max_bytes <= 0:
        return ""
    pointer = (
        ".reviewforge-context/graph-context.json (key: {key})"
        if context_dir
        else None
    )
    full_pointer = (
        ".reviewforge-context/graph-context.json (key: wave2)"
        if context_dir
        else None
    )
    sections: list[str] = []
    api = context.get("api_surface")
    if isinstance(api, dict) and api.get("status") in {"ok", "degraded"}:
        api_lines = ["Deterministic API-surface changes:"]
        candidates = [
            f"  - {item.get('symbol', '?')} (callers={item.get('caller_count', 0)})"
            for item in api.get("breaking_candidates", [])
            if isinstance(item, dict)
        ]
        api_lines.extend(
            render_section(
                "",
                candidates,
                15,
                pointer.format(key="api_surface.breaking_candidates") if pointer else None,
            ).splitlines()
        )
        added = api.get("added_nodes") if isinstance(api.get("added_nodes"), list) else []
        api_lines.extend(
            render_section(
                "",
                [f"  - added {name}" for name in added],
                10,
                pointer.format(key="api_surface.added_nodes") if pointer else None,
            ).splitlines()
        )
        removed = api.get("removed_nodes") if isinstance(api.get("removed_nodes"), list) else []
        api_lines.extend(
            render_section(
                "",
                [f"  - removed {name}" for name in removed],
                10,
                pointer.format(key="api_surface.removed_nodes") if pointer else None,
            ).splitlines()
        )
        sections.append("\n".join(api_lines))

    flow = context.get("flows")
    if isinstance(flow, dict):
        flow_lines: list[str] = []
        flow_items = flow.get("top") if isinstance(flow.get("top"), list) else []
        for item in flow_items:
            if not isinstance(item, dict):
                continue
            try:
                criticality = float(item.get("criticality", 0) or 0)
            except (TypeError, ValueError):
                criticality = 0.0
            flow_lines.append(
                f"  - {item.get('entry_point', '?')} (criticality={criticality:.3f})"
            )
        if flow_lines:
            sections.append(
                "\n".join(
                    [
                        "Critical flows reached by this change:",
                        render_section(
                            "",
                            flow_lines,
                            15,
                            pointer.format(key="flows.top") if pointer else None,
                        ),
                    ]
                )
            )

    arch = context.get("architecture")
    if isinstance(arch, dict):
        hubs = [
            str(item.get("qualified_name", "?"))
            for item in arch.get("hubs_touched", [])
            if isinstance(item, dict)
        ]
        bridges = [
            str(item.get("qualified_name", "?"))
            for item in arch.get("bridges_touched", [])
            if isinstance(item, dict)
        ]
        crossed = arch.get("communities_crossed", 0)
        if hubs or bridges or crossed:
            arch_lines = ["Architecture facts:"]
            if len(hubs) <= 15:
                arch_lines.append(f"  - hubs: {', '.join(hubs)}")
            else:
                arch_lines.append(
                    render_section(
                        "  - hubs:",
                        hubs,
                        15,
                        pointer.format(key="architecture.hubs_touched") if pointer else None,
                    )
                )
            if len(bridges) <= 15:
                arch_lines.append(f"  - bridges: {', '.join(bridges)}")
            else:
                arch_lines.append(
                    render_section(
                        "  - bridges:",
                        bridges,
                        15,
                        pointer.format(key="architecture.bridges_touched") if pointer else None,
                    )
                )
            arch_lines.append(f"  - community boundaries crossed: {crossed}")
            sections.append("\n".join(arch_lines))

    return _byte_cap_with_pointer(
        "\n".join(sections),
        max_bytes,
        full_pointer,
    )


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


def _build_single_pi_prefix(ctx: StageContext) -> str:
    """Build the shared non-diff prefix for single-pi prompts."""
    metadata = ctx.metadata or (
        read_json(ctx.artifacts.metadata) if ctx.artifacts.metadata.exists() else {}
    )
    context_dir = ctx.extras.get("context_staging_dir")
    staging_index = ctx.extras.get("context_staging_index")

    def pointer(filename: str, key: str) -> str | None:
        if not context_dir:
            return None
        return f".reviewforge-context/{filename} (key: {key})"

    parts = [
        f"Single-call reasoning review for Azure DevOps PR #{ctx.cfg.pr_id}.",
        "Return only the rich ReviewResult JSON object defined in the system prompt.",
    ]
    if isinstance(staging_index, dict) and context_dir:
        files = [
            f"  - {name}: {info.get('description', '')}"
            for name, info in sorted(staging_index.items())
            if isinstance(info, dict)
        ]
        parts.append(
            "\nDeterministic context files:\n"
            + "\n".join(files)
            + "\nInline sections are authoritative summaries; read the referenced files for complete data."
        )
    if metadata:
        parts += ["\nRepository/project metadata:", json.dumps(metadata, ensure_ascii=False)]

    changed_files = list(getattr(ctx.state, "files", []) if ctx.state is not None else [])
    if not changed_files and getattr(ctx, "files_text", ""):
        changed_files = [line for line in ctx.files_text.splitlines() if line]
    if changed_files and len(changed_files) > _CONTEXT_MAX_FILES:
        parts.append(
            render_section(
                "\nChanged files:",
                changed_files,
                _CONTEXT_MAX_FILES,
                pointer("changed-files.json", "all entries"),
            )
        )
    else:
        files_text = getattr(ctx, "files_text", "") or "\n".join(changed_files) or "(no changed files)"
        parts += ["\nChanged files:", files_text]

    all_commits = _all_commit_lines(ctx)
    if all_commits:
        parts.append(
            render_section(
                "\nCommits in this PR:",
                all_commits,
                getattr(ctx.cfg, "commit_context_max", 50),
                pointer("commits.txt", "commits"),
            )
        )

    for label, value, filename in (
        ("Linked work items", ctx.extras.get("wi_context", []), "work-items.json"),
        ("Existing PR comments", ctx.extras.get("thread_context", []), "threads.json"),
    ):
        if value:
            parts.append(
                render_section(
                    f"\n{label}:",
                    value if isinstance(value, list) else [value],
                    _CONTEXT_MAX_ITEMS,
                    pointer(filename, "all entries"),
                )
            )

    if review_context := ctx.extras.get("review_context"):
        review_inline = dict(review_context) if isinstance(review_context, dict) else review_context
        review_pointers: list[str] = []
        if isinstance(review_inline, dict):
            review_inline = dict(review_inline)
            for key in ("previousComments", "activeComments", "resolvedComments", "changedCommits", "changedFiles"):
                values = review_inline.get(key)
                if isinstance(values, list) and len(values) > _CONTEXT_MAX_REVIEW_ITEMS:
                    review_inline[key] = values[:_CONTEXT_MAX_REVIEW_ITEMS]
                    if context_dir:
                        review_pointers.append(
                            f"…and {len(values) - _CONTEXT_MAX_REVIEW_ITEMS} more — full data: "
                            f".reviewforge-context/review-state.json (key: {key})"
                        )
        parts.append(
            "\nDeterministic review state:\n"
            + json.dumps(review_inline, ensure_ascii=False, sort_keys=True)
            + ("\n" + "\n".join(review_pointers) if review_pointers else "")
        )
        feedback = review_context.get("previousFeedback", []) if isinstance(review_context, dict) else []
        if feedback:
            if len(feedback) <= _CONTEXT_MAX_ITEMS:
                parts += [
                    "\nPrevious review feedback:\n",
                    json.dumps(feedback, ensure_ascii=False, sort_keys=True),
                ]
            else:
                parts.append(
                    render_section(
                        "\nPrevious review feedback:",
                        feedback,
                        _CONTEXT_MAX_ITEMS,
                        pointer("review-state.json", "previousFeedback"),
                    )
                )
            parts.append(
                "\nDo not re-raise dismissed findings unless the implicated code changed in THIS diff. "
                "Treat fixed findings as addressed, but flag them when reintroduced and set regression=true."
            )

    if crg_analysis := ctx.extras.get("crg_analysis"):
        _crg_summary = _format_crg_context(
            crg_analysis,
            getattr(ctx.cfg, "crg_context_max_bytes", 8192),
            context_dir,
        )
        if _crg_summary:
            parts += ["\nDeterministic graph context (Tree-sitter code-review graph):\n" + _crg_summary]
    if graph_context := ctx.extras.get("graph_context"):
        if any(
            getattr(ctx.cfg, name, False)
            for name in ("graph_api_diff", "graph_flows", "graph_arch")
        ):
            wave2 = _format_wave2_context(
                graph_context,
                getattr(ctx.cfg, "graph_context_max_bytes", 12288),
                context_dir,
            )
            if wave2:
                parts += ["\n" + wave2]
    return "\n".join(parts)


def _reduce_diff(diff_text: str, max_bytes: int) -> tuple[str, bool]:
    """Deterministically keep changed hunks within ``max_bytes``.

    Each file receives an equal share of the byte budget. Changed lines are
    preferred over ``diff --git`` metadata; headers are included whenever the
    share can accommodate them. A final UTF-8-safe prefix is a defensive cap.
    """
    if max_bytes <= 0:
        return "", bool(diff_text)
    encoded = diff_text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return diff_text, False

    sections = [section for section in diff_text.split("diff --git ") if section]
    if not sections:
        return encoded[:max_bytes].decode("utf-8", "ignore"), True

    pieces: list[str] = []
    remaining = max_bytes
    for index, section in enumerate(sections):
        lines = section.splitlines()
        if not lines:
            continue
        header = f"diff --git {lines[0]}"
        changed_lines = [
            line for line in lines[1:]
            if (line.startswith("+") or line.startswith("-"))
            and not line.startswith(("+++", "---"))
        ]
        body = "\n".join(changed_lines) or "\n".join(lines[1:])
        sections_left = len(sections) - index
        share = remaining // sections_left
        header_bytes = len(header.encode("utf-8")) + 1
        if body and share > header_bytes:
            piece = header + "\n" + body.encode("utf-8")[: share - header_bytes].decode("utf-8", "ignore")
        else:
            piece = _utf8_prefix(body or header, share)
        if piece:
            pieces.append(piece.rstrip())
            used = len(piece.encode("utf-8"))
            remaining = max(0, remaining - used - 1)

    result = _utf8_prefix("\n".join(pieces), max_bytes)
    return result, True


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


def _commit_lines(ctx: StageContext) -> list[str]:
    """Return the historical capped commit view used by legacy callers."""
    return _all_commit_lines(ctx)[:getattr(ctx.cfg, "commit_context_max", 50)]


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
    if findings:
        for finding in findings:
            location = finding.get("file") or "general"
            if finding.get("line"):
                location = f"{location}:{finding['line']}"
            lines.append(f"- [{finding.get('severity', 'minor')}] {finding.get('title', '')} ({location})")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Merged uncertainties across all chunks:")
    if uncertainties:
        for item in uncertainties:
            lines.append(f"- {item.get('topic', '')}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("Return only the chunk-synthesis JSON object defined in the system prompt.")
    return "\n".join(lines)


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
        chunks = _diff_chunks(diff_text, cfg.max_diff_bytes)
        started_at = time.time()
        reasoning_started = time.perf_counter()
        chunk_usage: list[TokenUsage] = []

        if len(chunks) == 1:
            output_path = ctx.artifacts.raw_dir / "fast-review.json"
            ctx.pi.run_json(cfg.fast_review_prompt_path, _build_single_pi_instruction(ctx), output_path, "single-pi reasoning")
            raw = read_json(output_path)
            if raw is None:
                raise ReasoningEngineError("single-pi reasoning produced no JSON", details={"output_path": str(output_path)})
            try:
                result = ReviewResult.model_validate(raw)
            except Exception as exc:
                raise SchemaValidationError("single-pi response does not match ReviewResult schema", details={"error": str(exc), "output_path": str(output_path)}) from exc
        else:
            findings = []
            uncertainties = []
            seen: set[tuple[str | None, int | None, str]] = set()
            previous_tokens = _runner_usage(ctx.pi)
            repeat_shared_prefix = not cfg.pi_session_enabled or cfg.pi_session_clear
            for index, chunk in enumerate(chunks, 1):
                output_path = ctx.artifacts.raw_dir / f"fast-review-{index}.json"
                ctx.pi.run_json(
                    cfg.fast_review_prompt_path,
                    _build_chunk_instruction(
                        ctx,
                        chunk,
                        index,
                        len(chunks),
                        include_shared_prefix=repeat_shared_prefix,
                    ),
                    output_path,
                    f"single-pi chunk {index}/{len(chunks)}",
                )
                raw = read_json(output_path)
                try:
                    partial = ChunkResult.model_validate(raw)
                except Exception as exc:
                    raise SchemaValidationError(
                        "single-pi chunk response does not match ChunkResult schema",
                        details={"error": str(exc), "output_path": str(output_path)},
                    ) from exc
                current_tokens = _runner_usage(ctx.pi)
                chunk_usage.append(
                    TokenUsage(
                        input=max(0, current_tokens.get("in", 0) - previous_tokens.get("in", 0)),
                        output=max(0, current_tokens.get("out", 0) - previous_tokens.get("out", 0)),
                        total=max(0, current_tokens.get("total", 0) - previous_tokens.get("total", 0)),
                    )
                )
                previous_tokens = current_tokens
                for finding in partial.findings:
                    key = (finding.file, finding.line, _normalize_title(finding.title))
                    if key not in seen:
                        seen.add(key)
                        findings.append(finding.model_dump(by_alias=True))
                uncertainties.extend(item.model_dump(by_alias=True) for item in partial.uncertainties)
            synthesis = self._synthesize(ctx, len(chunks), findings, uncertainties)
            if synthesis is not None:
                payload: dict[str, Any] = {
                    "review_summary": synthesis.review_summary.model_dump(),
                    "verification_summary": synthesis.verification_summary.model_dump(),
                    "pr_summary": synthesis.pr_summary.model_dump(),
                    "good_practices": [gp.model_dump() for gp in synthesis.good_practices],
                }
            else:
                ctx.extras["_synthesis_fallback"] = True
                payload = {
                    "review_summary": {"summary": f"Reviewed {len(chunks)} coherent diff chunks."},
                    "verification_summary": {"summary": "Reviewed each deterministic unified-diff chunk.", "approach": "chunked diff review"},
                    "pr_summary": {"implementation_summary": f"Reviewed {len(chunks)} unified-diff chunks."},
                }
            payload["findings"] = findings
            payload["uncertainties"] = uncertainties
            result = ReviewResult.model_validate(payload)

        reasoning_duration_ms = int((time.perf_counter() - reasoning_started) * 1000)
        tokens = _runner_usage(ctx.pi)
        ctx.last_token_usage = tokens
        finished_at = time.time()
        result = self._enrich_metadata(result, cfg, started_at, finished_at, tokens)
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
