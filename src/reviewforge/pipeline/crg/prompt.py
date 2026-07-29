"""CRG-specific single-Pi prompt sections."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

_CRG_MAX_PRIORITIES = 5
_CRG_MAX_FUNCTIONS = 15
_CRG_MAX_PATHS = 30
_CRG_MAX_TEST_GAPS = 15


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


def build_crg_section(
    analysis: dict[str, Any],
    max_bytes: int,
    context_dir: Path | None = None,
    render_section: Callable[..., str] | None = None,
    byte_cap_with_pointer: Callable[..., str] | None = None,
) -> str:
    """Format the complete CRG analysis as a bounded progressive summary."""
    if render_section is None or byte_cap_with_pointer is None:
        from ...reasoning.single_pi import (
            _byte_cap_with_pointer,
            render_section as _render_section,
        )
        render_section = _render_section
        byte_cap_with_pointer = _byte_cap_with_pointer
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
    return byte_cap_with_pointer(
        "\n".join(lines),
        max_bytes,
        pointer.format(key="full") if pointer else None,
    )


def build_wave2_section(
    context: dict[str, Any],
    max_bytes: int,
    context_dir: Path | None = None,
    render_section: Callable[..., str] | None = None,
    byte_cap_with_pointer: Callable[..., str] | None = None,
) -> str:
    """Format wave-two graph context into progressive-disclosure sections."""
    if render_section is None or byte_cap_with_pointer is None:
        from ...reasoning.single_pi import (
            _byte_cap_with_pointer,
            render_section as _render_section,
        )
        render_section = _render_section
        byte_cap_with_pointer = _byte_cap_with_pointer
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

    return byte_cap_with_pointer(
        "\n".join(sections),
        max_bytes,
        full_pointer,
    )
