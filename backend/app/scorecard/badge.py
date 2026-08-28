"""Self-contained SVG reliability badge (shields.io-style, no external service).

Rendered by GET /api/badge/{agent_version}.svg and embeddable in any README via
Markdown. Kept dependency-free so it works offline and in CI.
"""
from typing import Tuple

# Certification status -> (short label, hex color) for the colored half.
_STATUS_STYLE = {
    "UNSAFE": ("UNSAFE", "#e11d48"),            # rose
    "EVALUATION_INCOMPLETE": ("INCOMPLETE", "#f59e0b"),  # amber
    "NEEDS_REVIEW": ("REVIEW", "#f59e0b"),      # amber
    "PRODUCTION_READY": ("READY", "#10b981"),   # emerald
}
_UNRATED_COLOR = "#9ca3af"  # slate


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _text_width(s: str) -> int:
    """Rough pixel width for a ~11px sans label, plus horizontal padding."""
    return int(len(s) * 6.6) + 12


def badge_for_scorecard(scorecard) -> Tuple[str, str, str]:
    """Map a Scorecard to (label, message, color) for the badge."""
    short, color = _STATUS_STYLE.get(scorecard.safety_status, (scorecard.safety_status, _UNRATED_COLOR))
    message = f"{scorecard.overall_score}/100 · {short}"
    return "AgentCI", message, color


def build_badge_svg(label: str, message: str, color: str) -> str:
    """Return a flat, two-segment SVG badge: gray label + colored message."""
    label = _escape(label)
    message = _escape(message)
    label_w = _text_width(label)
    msg_w = _text_width(message)
    total = label_w + msg_w
    # Text is drawn in a 10x-scaled space (scale(.1)) for crisp sub-pixel centering,
    # the same trick shields.io uses.
    label_cx = label_w * 5
    msg_cx = (label_w + msg_w // 2) * 10
    label_len = (label_w - 12) * 10
    msg_len = (msg_w - 12) * 10
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="20" '
        f'role="img" aria-label="{label}: {message}">'
        f'<linearGradient id="s" x2="0" y2="100%">'
        f'<stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{total}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)">'
        f'<rect width="{label_w}" height="20" fill="#374151"/>'
        f'<rect x="{label_w}" width="{msg_w}" height="20" fill="{color}"/>'
        f'<rect width="{total}" height="20" fill="url(#s)"/></g>'
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="110" '
        f'text-rendering="geometricPrecision">'
        f'<text x="{label_cx}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{label_len}">{label}</text>'
        f'<text x="{label_cx}" y="140" transform="scale(.1)" textLength="{label_len}">{label}</text>'
        f'<text x="{msg_cx}" y="150" fill="#010101" fill-opacity=".3" '
        f'transform="scale(.1)" textLength="{msg_len}">{message}</text>'
        f'<text x="{msg_cx}" y="140" transform="scale(.1)" textLength="{msg_len}">{message}</text>'
        f'</g></svg>'
    )
