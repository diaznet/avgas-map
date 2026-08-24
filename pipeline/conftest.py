"""Pytest configuration: make the `avgasmap` package importable.

Adds the pipeline/ directory (this file's directory) to sys.path so tests can
`import avgasmap...` without installing the package.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
