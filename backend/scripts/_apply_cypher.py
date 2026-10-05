"""Package-private utility: apply one ``*.cypher`` migration file."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StatementError:
    statement: str
    exception: BaseException
    index: int  # 1-indexed position within the file


@dataclass
class ApplyResult:
    statements_run: int = 0
    errors: list[StatementError] = field(default_factory=list)


class CypherStatementError(Exception):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__(f"Cypher statement error: {len(self.errors)} statement(s) failed")


def _split_statements(content: str) -> list[str]:
    # Strip // lines and lone -- markers BEFORE splitting on ';' so semicolons inside
    # comment prose cannot orphan trailing non-comment text.
    non_comment_lines = [
        line
        for line in content.splitlines()
        if line.strip() and not line.strip().startswith("//") and line.strip() != "--"
    ]
    return [
        cleaned
        for raw in "\n".join(non_comment_lines).split(";")
        if (cleaned := " ".join(raw.splitlines()).strip())
    ]


def apply_cypher_file(
    driver: Any,
    file_path: Path,
    *,
    log: logging.Logger | None = None,
) -> ApplyResult:
    """Apply every statement in ``file_path``. No rollback — Neo4j commits per-statement."""
    logger = log or logging.getLogger(__name__)
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"migration file not found: {path}")

    statements = _split_statements(path.read_text(encoding="utf-8"))
    logger.info("Loaded %d statement(s) from %s", len(statements), path.name)

    result = ApplyResult()
    with driver.session() as session:
        for i, stmt in enumerate(statements, start=1):
            try:
                session.run(stmt)
                result.statements_run += 1
                logger.info("  [%d/%d] OK: %s", i, len(statements), stmt[:80])
            except Exception as exc:  # noqa: BLE001
                logger.error("  [%d/%d] FAILED: %s", i, len(statements), stmt[:80])
                logger.error("  Statement error from Neo4j driver: %s", exc)
                err = StatementError(statement=stmt, exception=exc, index=i)
                result.errors.append(err)
                raise CypherStatementError(result.errors) from exc

    return result
