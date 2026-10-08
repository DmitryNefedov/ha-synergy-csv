"""Human-readable rendering of an UploadSummary (pure, easily tested)."""

from __future__ import annotations

from .service import UploadSummary

_DATE = "%d/%m/%Y"


def format_summary(summary: UploadSummary) -> str:
    lines = [
        f"**Range:** {summary.first:{_DATE}} – {summary.last:{_DATE}}",
        f"**Readings:** {summary.new:,} new, {summary.replaced:,} replaced",
        f"**Registers:** {', '.join(summary.registers)}",
        f"**Gaps:** {_format_gaps(summary)}",
    ]
    if summary.ignored_columns:
        lines.append(f"**Ignored columns:** {', '.join(summary.ignored_columns)}")
    return "\n\n".join(lines)


def _format_gaps(summary: UploadSummary) -> str:
    if not summary.gaps:
        return "none"
    missing = sum(gap.count for gap in summary.gaps)
    first = summary.gaps[0].start
    places = len(summary.gaps)
    return f"{missing:,} missing intervals in {places} places (first at {first:%d/%m/%Y %H:%M})"
