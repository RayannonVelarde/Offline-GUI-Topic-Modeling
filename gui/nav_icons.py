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
}


def make_nav_icon(page_id: str, *, size: int = 18, color_hex: str = "#475569") -> QIcon:
    """Render a crisp pixmap icon at logical `size` (respects device pixel ratio)."""
    inner = _SVG_PARTS.get(page_id)
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
