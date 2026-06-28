"""backend/repositories -- data access layer.

Each submodule wraps a specific persistence concern (Neo4j, TimescaleDB,
Postgres) and exposes a small set of well-named functions or classes.

Conventions:
- Import via ``from repositories import <submodule>`` OR
  ``from repositories.<submodule> import <symbol>`` (both work).
- The package re-exports nothing from __init__; callers pick a submodule
  explicitly to keep the dependency surface obvious.
- Neo4j-backed modules (rtu_sensor_repo, topology_repo, device_metric_repo)
  take a Neo4j driver as a constructor argument or via database.get_db()
  inside free functions. Test them with the mock_neo4j_driver fixture from
  backend/tests/conftest.py.

Submodules:
- metric_repo         -- TimescaleDB / Postgres metric value history
- rtu_sensor_repo     -- legacy RTU/Sensor Neo4j persistence (PR1)
- topology_repo       -- CI topology queries (nodes, relationships, owners)
- user_repo           -- user CRUD
- device_metric_repo  -- generic Device+Metric Neo4j persistence (PR3a,
                          replaces RTU/Sensor for new MQTT messages)
"""
