"""
Minimal stroke SVG nav icons (single family, 24×24 viewBox) rendered via QtSvg.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

# Inner SVG elements only (stroke applied on root <svg>)
_SVG_PARTS: dict[str, str] = {
    "home": """
<path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
<polyline points="9 22 9 12 15 12 15 22"/>
""",
    "jobs": """
<line x1="8" y1="6" x2="21" y2="6"/>
<line x1="8" y1="12" x2="21" y2="12"/>
<line x1="8" y1="18" x2="21" y2="18"/>
<line x1="3" y1="6" x2="3.01" y2="6"/>
<line x1="3" y1="12" x2="3.01" y2="12"/>
<line x1="3" y1="18" x2="3.01" y2="18"/>
""",
    "review": """
<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
<polyline points="14 2 14 8 20 8"/>
<line x1="16" y1="13" x2="8" y2="13"/>
<line x1="16" y1="17" x2="8" y2="17"/>
<line x1="10" y1="9" x2="8" y2="9"/>
""",
    "settings": """
<line x1="4" y1="21" x2="4" y2="14"/>
<line x1="4" y1="10" x2="4" y2="3"/>
<line x1="12" y1="21" x2="12" y2="12"/>
<line x1="12" y1="8" x2="12" y2="3"/>
<line x1="20" y1="21" x2="20" y2="16"/>
<line x1="20" y1="12" x2="20" y2="3"/>
<line x1="2" y1="14" x2="6" y2="14"/>
<line x1="10" y1="8" x2="14" y2="8"/>
<line x1="18" y1="16" x2="22" y2="16"/>
""",
    # Open folder: same 24×24 stroke language as nav icons (Lucide-style folder-open).
    "folder_open": """
<path d="m6 14 1.5-2.4A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.55 6a2 2 0 0 1-1.94 1.5H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3.17a2 2 0 0 1 1.66.9l.83 1.2H18a2 2 0 0 1 2 2v2"/>
""",
    # Disclosure chevrons (inline log expand/collapse).
    "chevron_right": """
<polyline points="9 18 15 12 9 6"/>
""",
    "chevron_down": """
<polyline points="6 9 12 15 18 9"/>
""",
    # Document with lines (inline job log toggle on Home table).
    "log_output": """
<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
<polyline points="14 2 14 8 20 8"/>
<line x1="8" y1="13" x2="16" y2="13"/>
<line x1="8" y1="17" x2="16" y2="17"/>
<line x1="8" y1="9" x2="11" y2="9"/>
""",
    # Open in external app / default handler (Review column headers).
    "open_external": """
<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
<polyline points="15 3 21 3 21 9"/>
<line x1="10" y1="14" x2="21" y2="3"/>
""",
    # Minimal X (Lucide-style). Used for the Home row "Remove from list" button.
    "x_close": """
<line x1="18" y1="6" x2="6" y2="18"/>
<line x1="6" y1="6" x2="18" y2="18"/>
""",
    # Lucide-style pencil/edit icon. Used for Review page per-panel edit toggle.
    "pencil": """
<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
<path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
""",
    # Marker/highlighter icon. Used for Review page sync-highlight toggle.
    "highlighter": """
<path d="M15.5 2.1 21.9 8.5 8.9 21.5 2.5 21.9l.4-6.4z"/>
<line x1="11" y1="13" x2="14" y2="10"/>
""",
}


def _render_stroke_icon(part_id: str, *, size: int, color_hex: str) -> QIcon:
    """Shared renderer: 24×24 viewBox, stroke 2, round caps (matches sidebar nav icons)."""
    inner = _SVG_PARTS.get(part_id)
    if inner is None:
        return QIcon()

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color_hex}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
{inner.strip()}
</svg>"""
    data = svg.encode("utf-8")
    renderer = QSvgRenderer(data)
    if not renderer.isValid():
        return QIcon()

    app = QApplication.instance()
    dpr = float(app.devicePixelRatio()) if app is not None else 1.0
    dpr = max(1.0, dpr)
    px = max(1, int(round(size * dpr)))
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return QIcon(pm)


def make_nav_icon(page_id: str, *, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Render a crisp pixmap icon at logical `size` (respects device pixel ratio)."""
    return _render_stroke_icon(page_id, size=size, color_hex=color_hex)


def make_folder_open_icon(*, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Stroke folder-open icon matching nav icon family (for Home table action column)."""
    return _render_stroke_icon("folder_open", size=size, color_hex=color_hex)


def make_disclosure_chevron_icon(*, expanded: bool, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Right = collapsed, down = expanded (same stroke family as nav icons)."""
    key = "chevron_down" if expanded else "chevron_right"
    return _render_stroke_icon(key, size=size, color_hex=color_hex)


def make_log_output_icon(*, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Document-with-lines icon for inline job log show/hide (Home filename row)."""
    return _render_stroke_icon("log_output", size=size, color_hex=color_hex)


def make_open_external_icon(*, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Window-with-arrow-out icon: open file in default application (Review headers)."""
    return _render_stroke_icon("open_external", size=size, color_hex=color_hex)


def make_remove_icon(*, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Minimal X icon for the Home row 'Remove from list' action."""
    return _render_stroke_icon("x_close", size=size, color_hex=color_hex)


def make_pencil_icon(*, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Pencil/edit icon for the Review page per-panel edit toggle."""
    return _render_stroke_icon("pencil", size=size, color_hex=color_hex)


def make_highlighter_icon(*, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Marker/highlighter icon for the Review page sync-highlight toggle."""
    return _render_stroke_icon("highlighter", size=size, color_hex=color_hex)
