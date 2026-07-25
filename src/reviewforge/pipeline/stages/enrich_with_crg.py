"""Stage: enrich context with a Tree-sitter code-review graph (CRG).

Runs between :class:`PrepareRepositoryStage` and
:class:`ExecuteReasoningEngineStage`. Uses the optional ``code-review-graph``
PyPI package to build a lightweight SQLite knowledge graph from the
checked-out working tree, then analyses which functions were changed, their
blast radius, affected flows, test gaps, and risk scores.

The result is stored in ``ctx.extras["crg_analysis"]`` so that
:func:`~reviewforge.reasoning.single_pi._build_single_pi_prefix` can
forward it as structured context to the model. It is also written as
``crg-analysis.json`` in the run artifact directory.

This stage MUST NOT raise on any CRG failure. Any error degrades
gracefully to today's behavior with a :func:`~reviewforge.runlog.warning`.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ...runlog import info as _log, warning as log_warning
from ..stage import Stage, StageContext


class EnrichWithCrgStage(Stage):
    """Build a Tree-sitter knowledge graph and analyse the PR diff.

    Produces ``ctx.extras["crg_analysis"]`` — a dict with keys
    ``summary``, ``risk_score``, ``changed_functions``, ``affected_flows``,
    ``test_gaps``, and ``review_priorities`` — for downstream prompt injection.
    """

    name = "enrich_with_crg"

    def should_run(self, ctx: StageContext) -> bool:
        if not ctx.cfg.crg_enabled:
            return False
        if ctx.state is None or not getattr(ctx.state, "repo_dir", None):
            return False
        return True

    def run(self, ctx: StageContext) -> dict[str, Any]:  # noqa: PLR0912 - graceful-degrade
        repo_dir: Path = ctx.state.repo_dir
        changed_files: list[str] = list(getattr(ctx.state, "files", []))
        range_spec: str = getattr(ctx.state, "range_spec", "")

        try:
            from code_review_graph.graph import GraphStore
            from code_review_graph.incremental import full_build
            from code_review_graph.changes import analyze_changes, parse_git_diff_ranges
        except ImportError:
            log_warning(
                "CRG enrichment skipped: 'code-review-graph' package is not installed. "
                "Install it with: pip install code-review-graph"
            )
            return {"crg_status": "package_unavailable"}

        try:
            db_path = _crg_db_path(ctx)
            store = GraphStore(db_path)
            build_result = full_build(repo_dir, store)
            node_count: int = build_result.get("nodes", 0) if isinstance(build_result, dict) else 0
            _log(f"CRG graph built: {node_count} nodes from {repo_dir}")
        except Exception as exc:  # noqa: BLE001
            log_warning(f"CRG graph build failed ({type(exc).__name__}: {exc}); skipping enrichment")
            return {"crg_status": "build_failed", "crg_error": str(exc)}

        try:
            # Parse line ranges from the diff so CRG can pinpoint changed nodes
            # precisely. Pass the range_spec (e.g. "abc..def") as the git base.
            # Absolute paths are required by analyze_changes for correct lookup.
            root_str = str(repo_dir)
            if range_spec:
                raw_ranges = parse_git_diff_ranges(root_str, range_spec)
                # Remap relative keys to absolute paths for GraphStore lookups.
                changed_ranges: dict[str, list[tuple[int, int]]] = {
                    str(repo_dir / key): ranges
                    for key, ranges in raw_ranges.items()
                }
            else:
                changed_ranges = None

            abs_changed_files = [
                str(repo_dir / f) if not Path(f).is_absolute() else f
                for f in changed_files
            ]
            analysis = analyze_changes(
                store,
                abs_changed_files,
                changed_ranges=changed_ranges,
                repo_root=root_str,
            )
        except Exception as exc:  # noqa: BLE001
            log_warning(f"CRG analysis failed ({type(exc).__name__}: {exc}); skipping enrichment")
            return {"crg_status": "analysis_failed", "crg_error": str(exc)}

        try:
            _write_artifact(ctx, analysis)
        except Exception as exc:  # noqa: BLE001
            log_warning(f"CRG artifact write failed ({type(exc).__name__}: {exc}); continuing without artifact")

        ctx.extras["crg_analysis"] = analysis
        _log(
            f"CRG enrichment complete: risk_score={analysis.get('risk_score', 0):.2f}, "
            f"changed_functions={len(analysis.get('changed_functions', []))}, "
            f"test_gaps={len(analysis.get('test_gaps', []))}"
        )
        return {
            "crg_status": "ok",
            "crg_nodes": node_count,
            "crg_risk_score": analysis.get("risk_score", 0),
            "crg_changed_functions": len(analysis.get("changed_functions", [])),
            "crg_test_gaps": len(analysis.get("test_gaps", [])),
        }


def _crg_db_path(ctx: StageContext) -> Path:
    """Return a per-run SQLite path for the CRG graph, under raw/."""
    return ctx.artifacts.raw_dir / "crg.db"


def _write_artifact(ctx: StageContext, analysis: dict[str, Any]) -> None:
    """Serialise ``analysis`` to the ``crg-analysis.json`` artifact."""
    ctx.artifacts.crg_analysis.write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


__all__ = ["EnrichWithCrgStage"]
