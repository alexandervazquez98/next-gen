"""Atomic XLSX import package for Service Management.

Implements WU 6 (catalog workbook) and WU 7 (ticket workbook) — atomic,
template-driven imports with structured row/field/code errors and lock-aware
full-batch behavior. See ``openspec/changes/service-management-catalog/design.md``
for the canonical contract.
"""
