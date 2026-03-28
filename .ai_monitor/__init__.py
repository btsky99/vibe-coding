"""
FILE: .ai_monitor/__init__.py
DESCRIPTION: ai_monitor package bootstrap for pip installs.
"""

import sys
from pathlib import Path

# Keep legacy absolute imports like `import api.*` and `import src.*`
# working in both package mode and direct `python server.py` mode.
_pkg_dir = str(Path(__file__).resolve().parent)
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from ._version import __version__

__all__ = ["__version__"]
