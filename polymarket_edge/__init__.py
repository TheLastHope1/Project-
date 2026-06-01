"""Source-layout import shim for local `python -m polymarket_edge.cli` runs."""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "polymarket_edge"
if _SRC_PACKAGE.is_dir():
    __path__.append(str(_SRC_PACKAGE))  # type: ignore[name-defined]

