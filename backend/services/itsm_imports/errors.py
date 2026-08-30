"""Structured error contract for Service Management XLSX imports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


IMPORT_VALIDATION_FAILED = "validation_failed"
IMPORT_ERROR_CAP = 200


@dataclass(frozen=True)
class RowFieldError:
    row: int | None
    field: str
    code: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "field": self.field, "code": self.code, "reason": self.reason}


@dataclass
class ImportValidationError(Exception):
    errors: list[RowFieldError] = field(default_factory=list)
    error_count: int = 0
    status: str = IMPORT_VALIDATION_FAILED
    message: str = "Workbook validation failed; no records were imported."

    def __post_init__(self) -> None:
        if self.error_count == 0:
            self.error_count = len(self.errors)

    def add(self, *, row: int | None, field: str, code: str, reason: str) -> None:
        self.error_count += 1
        if len(self.errors) < IMPORT_ERROR_CAP:
            self.errors.append(RowFieldError(row=row, field=field, code=code, reason=reason))

    def has_errors(self) -> bool:
        return bool(self.errors)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "errors": [e.to_dict() for e in self.errors],
            "error_count": self.error_count,
        }


__all__ = ["IMPORT_ERROR_CAP", "IMPORT_VALIDATION_FAILED", "ImportValidationError", "RowFieldError"]
