"""MQTT subscriber loop — placeholder until PR2b rewrites the dispatch logic.

PR2b will replace this body with a router-driven loop that subscribes to
all registered parser patterns and dispatches messages via
:class:`TopicRouter`. The signature ``mqtt_subscriber_loop()`` is preserved
so callers (and the back-compat shim in ``services.mqtt_subscriber``) keep
importing the same symbol.
"""


async def mqtt_subscriber_loop() -> None:
    """Placeholder loop — raises until PR2b lands the router-driven version.

    Raises:
        NotImplementedError: Always. PR2b will replace this with the real
            implementation that subscribes to all registered parser patterns
            and dispatches through TopicRouter.
    """
    raise NotImplementedError(
        "Replaced in PR2b; see sdd/mqtt-format-generalization/design (topic_router + subscriber)"
    )
