"""Enable `python -m aiplatform_cli`."""
from __future__ import annotations

import sys

from aiplatform_cli.cli import main

if __name__ == "__main__":
    sys.exit(main())
