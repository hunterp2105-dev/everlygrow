import math
from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).resolve().parent.parent / "styles" / "theme.css"

_STAMP_VARIANTS = {
    "approved": "sg-stamp--approved",
    "review": "sg-stamp--review",
    "planned": "sg-stamp--planned",
    # The one glowing badge kind — reserved for a genuinely in-progress
    # state (a generation actually processing, a post actually publishing).
    # Never use this for a resting state, however important — see §18.1 (v2).
    "active": "sg-stamp--active",
}


def inject_theme() -> None:
    css = _CSS_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def stamp(label: str, kind: str = "approved") -> str:
    variant = _STAMP_VARIANTS[kind]
    return f'<span class="sg-stamp {variant}">{label}</span>'


def card_open(title: str | None = None, elevated: bool = False) -> None:
    """§16 visual-polish pass (2026-09-29): `elevated=True` is the ONE
    primary content area on a screen (see theme.css's .sg-card--elevated
    comment) — a deeper shadow and a lighter surface tone, never an
    accent color, since accent stays reserved for active states."""
    css_class = "sg-card sg-card--elevated" if elevated else "sg-card"
    st.markdown(f'<div class="{css_class}">', unsafe_allow_html=True)
    if title:
        st.markdown(f"### {title}")


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def empty_state(message: str) -> None:
    st.markdown(f'<div class="sg-empty-state">{message}</div>', unsafe_allow_html=True)


def metric_tile(value: str, label: str, warn: bool = False) -> str:
    """§16 visual-polish pass: a compact bordered tile for a cap/fraction
    shown inline alongside others (e.g. "3/5 posts today") — real cap
    strips (admin_panel._render_social_cap_strip) render several of these
    in a row instead of one long caption string. `warn=True` for an
    over-cap value — a flat color change, not the accent glow (that stays
    reserved for genuinely active/in-progress states, not a warning)."""
    variant = "sg-metric-tile sg-metric-tile--warn" if warn else "sg-metric-tile"
    return (
        f'<div class="{variant}">'
        f'<span class="sg-metric-tile-value">{value}</span>'
        f'<span class="sg-metric-tile-label">{label}</span>'
        f"</div>"
    )


def progress_line() -> str:
    """§16 visual-polish pass: a slim indeterminate progress sweep for a
    genuinely long-running wait (video generation) — pairs with
    stamp(..., "active"), never replaces it. Indeterminate on purpose:
    real completion % isn't knowable, so this never implies false
    precision the way a filled bar would."""
    return '<div class="sg-progress-line"></div>'


def _wrap_label(text: str, max_chars: int = 13) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def module_map_svg(hub_label: str, modules: list[dict]) -> str:
    """Circuit-diagram Module Map (§18.1 v2) — a hub node with trace lines
    fanning out to module nodes, arranged in a circle. Active modules'
    traces and nodes carry the accent glow; planned ones render dashed
    and dim. Lines are drawn hub-center to node-center *underneath* the
    opaque node/hub circles, so the fill naturally clips each trace to
    run edge-to-edge without needing separate trim geometry."""
    width, height = 640, 640
    cx, cy = width / 2, height / 2
    hub_r = 58
    node_r = 46
    orbit_r = 235

    count = len(modules)
    traces, nodes = [], []
    for i, module in enumerate(modules):
        angle = (2 * math.pi * i / count) - (math.pi / 2) if count else 0
        nx = cx + orbit_r * math.cos(angle)
        ny = cy + orbit_r * math.sin(angle)
        active = module["status"] == "active"
        trace_class = "sg-trace sg-trace--active" if active else "sg-trace"
        node_class = "sg-node sg-node--active" if active else "sg-node sg-node--planned"
        dot_class = "sg-node-dot sg-node-dot--active" if active else "sg-node-dot"
        label_class = "sg-node-label" if active else "sg-node-label sg-node-label--planned"
        sub_class = "sg-node-sublabel sg-node-sublabel--active" if active else "sg-node-sublabel"
        sub_text = "ACTIVE" if active else "PLANNED"
        label_lines = _wrap_label(module["name"])
        label_start_y = ny - 6 * (len(label_lines) - 1)
        label_tspans = "".join(
            f'<tspan x="{nx:.1f}" y="{label_start_y + i * 13:.1f}">{line}</tspan>' for i, line in enumerate(label_lines)
        )

        traces.append(f'<line class="{trace_class}" x1="{cx:.1f}" y1="{cy:.1f}" x2="{nx:.1f}" y2="{ny:.1f}" />')
        nodes.append(
            f'<g>'
            f'<circle class="{node_class}" cx="{nx:.1f}" cy="{ny:.1f}" r="{node_r}" />'
            f'<circle class="{dot_class}" cx="{nx:.1f}" cy="{ny - 14:.1f}" r="3.5" />'
            f'<text class="{label_class}" font-size="11" text-anchor="middle">{label_tspans}</text>'
            f'<text class="{sub_class}" x="{nx:.1f}" y="{label_start_y + len(label_lines) * 13 + 4:.1f}" font-size="9" text-anchor="middle">{sub_text}</text>'
            f'</g>'
        )

    return (
        f'<svg class="sg-module-map" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(traces)}'
        f'<circle class="sg-node-hub" cx="{cx}" cy="{cy}" r="{hub_r}" />'
        f'<text class="sg-node-hub-label" x="{cx}" y="{cy + 5}" font-size="16" text-anchor="middle">{hub_label}</text>'
        f'{"".join(nodes)}'
        f'</svg>'
    )
