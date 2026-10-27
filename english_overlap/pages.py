"""HTML rendering for the existing overlap practice page."""

from __future__ import annotations

import mimetypes
from pathlib import Path


def render_practice_page(root: str | Path, max_text_chars: int) -> str:
    del max_text_chars
    app_index = Path(root) / 'english_overlap' / 'static' / 'app' / 'index.html'
    if not app_index.is_file():
        raise FileNotFoundError('React application is not built. Run npm run build.')
    return app_index.read_text(encoding='utf-8')


def read_static_asset(name: str, *, root: str | Path | None = None) -> tuple[bytes, str] | None:
    if name.startswith('app/'):
        static_root = Path(root) if root is not None else Path(__file__).parent / 'static'
        app_root = (static_root / 'app').resolve()
        path = (app_root / name.removeprefix('app/')).resolve()
        if app_root not in path.parents or not path.is_file():
            return None
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    assets = {
        'shortcuts.js': ('text/javascript; charset=utf-8', Path(__file__).parent / 'static' / 'shortcuts.js'),
        'learning.js': ('text/javascript; charset=utf-8', Path(__file__).parent / 'static' / 'learning.js'),
        'statistics_distribution.js': ('text/javascript; charset=utf-8', Path(__file__).parent / 'static' / 'statistics_distribution.js'),
        'overlap.js': ('text/javascript; charset=utf-8', Path(__file__).parent / 'static' / 'overlap.js'),
    }
    item = assets.get(name)
    if item is None:
        return None
    content_type, path = item
    return path.read_bytes(), content_type
