"""Idempotently link ICMP latency/jitter sidecar metrics to existing CIs.

Run from the repository root with:
    python backend/scripts/migrate_icmp_sidecar_metrics.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add backend to path for direct script execution.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from repositories import topology_repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    logger.info("Starting ICMP sidecar metric migration...")
    topology_repo.migrate_icmp_sidecar_metrics()
    logger.info("ICMP sidecar metric migration complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
