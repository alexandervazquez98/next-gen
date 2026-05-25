"""Non-production polling load simulator entrypoint.

This module intentionally does nothing on import. Run it as a script to produce
synthetic benchmark evidence before enabling heavier DB-backed tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.polling_host_benchmark import main


if __name__ == "__main__":
    raise SystemExit(main())
