"""Run the read-only legacy Event discriminator audit."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.legacy_event_discriminator_audit import (  # noqa: E402
    result_to_json_dict,
    result_to_markdown,
    run_legacy_event_discriminator_audit,
)


def _load_driver():
    return importlib.import_module("database").get_db()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit legacy Event discriminator risks without mutating data."
    )
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--output", help="Optional output path. Prints to stdout when omitted.")
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of Event rows to inspect."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = run_legacy_event_discriminator_audit(_load_driver(), limit=args.limit)
    if args.format == "json":
        rendered = json.dumps(result_to_json_dict(result), indent=2, sort_keys=True) + "\n"
    else:
        rendered = result_to_markdown(result)

    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
