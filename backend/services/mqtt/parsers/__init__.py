"""Parser registry — pluggable MQTT payload parsers.

The subscriber loop (PR2) builds a :class:`TopicRouter` from the parsers in
this registry. New device families add a single file under ``parsers/`` and
one ``register(...)`` line at the bottom of this module.

Auto-registration keeps the loop ignorant of parser discovery — it just asks
``all_parsers()`` at startup.
"""

from __future__ import annotations

from .base import Parser

__all__ = ["Parser", "register", "get", "all_parsers", "_clear_registry"]


_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> None:
    """Add ``parser`` to the global registry.

    Args:
        parser: A :class:`Parser` instance with a unique :attr:`Parser.name`.

    Raises:
        ValueError: A parser with the same name is already registered.
    """
    if parser.name in _REGISTRY:
        raise ValueError(f"Parser '{parser.name}' already registered")
    _REGISTRY[parser.name] = parser


def get(name: str) -> Parser:
    """Look up a registered parser by name.

    Args:
        name: The :attr:`Parser.name` to look up.

    Returns:
        The registered :class:`Parser` instance.

    Raises:
        KeyError: No parser is registered under ``name``.
    """
    return _REGISTRY[name]


def all_parsers() -> list[Parser]:
    """Return all currently registered parsers, in registration order."""
    return list(_REGISTRY.values())


def _clear_registry() -> None:
    """Reset the registry. Test-only — production code must not use this."""
    _REGISTRY.clear()


# Auto-register built-in parsers. New device families add their own
# ``register(...)`` line here.
from services.mqtt.parsers.bliiot_s475e import BliiotS475EParser  # noqa: E402

register(BliiotS475EParser())
