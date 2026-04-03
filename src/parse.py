from __future__ import annotations

from pathlib import Path
from typing import Any

from .pipeline import _parse_file as parse_file
from .pipeline import _python_parse as parse_python
from .pipeline import _tree_parse as parse_tree_sitter


def parse_files(path: Path, root: Path, cache_dir: Path) -> dict[str, Any] | None:
    return parse_file(path, root, cache_dir)

