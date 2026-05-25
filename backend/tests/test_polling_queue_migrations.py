from types import SimpleNamespace


def test_polling_migration_defines_schema_migrations_and_queue_tables():
    from polling.migrations import SCHEMA_MIGRATIONS_SQL, POLLING_QUEUE_MIGRATION

    assert "CREATE TABLE IF NOT EXISTS schema_migrations" in SCHEMA_MIGRATIONS_SQL
    sql = POLLING_QUEUE_MIGRATION.sql
    assert "CREATE TABLE IF NOT EXISTS poll_cycles" in sql
    assert "CREATE TABLE IF NOT EXISTS poll_task_queue" in sql
    assert "CREATE TABLE IF NOT EXISTS poll_result_queue" in sql
    assert "FOR UPDATE SKIP LOCKED" not in sql
    assert "idx_poll_task_claim" in sql
    assert "idx_poll_result_claim" in sql
    assert "uq_poll_result_idempotency_key" in sql
    assert "CREATE TABLE IF NOT EXISTS metric_sample_receipts" in sql
    assert "idempotency_key TEXT PRIMARY KEY" in sql


class FakeConnection:
    def __init__(self, applied=()):
        self.applied = set(applied)
        self.executed = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.executed.append((sql, params or {}))
        if "SELECT version FROM schema_migrations" in sql:
            return [SimpleNamespace(version=version) for version in self.applied]
        if "INSERT INTO schema_migrations" in sql and params:
            self.applied.add(params["version"])
        return []


class FakeEngine:
    def __init__(self, conn):
        self.conn = conn

    def begin(self):
        conn = self.conn

        class _Ctx:
            def __enter__(self):
                return conn

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


def test_run_pending_migrations_records_unapplied_versions_only():
    from polling.migrations import POLLING_QUEUE_MIGRATION, run_pending_migrations

    conn = FakeConnection()
    applied = run_pending_migrations(FakeEngine(conn))

    assert applied == [POLLING_QUEUE_MIGRATION.version]
    assert any("CREATE TABLE IF NOT EXISTS schema_migrations" in sql for sql, _ in conn.executed)
    assert any("CREATE TABLE IF NOT EXISTS poll_task_queue" in sql for sql, _ in conn.executed)
    assert any(params.get("version") == POLLING_QUEUE_MIGRATION.version for _, params in conn.executed)

    conn.executed.clear()
    applied_again = run_pending_migrations(FakeEngine(conn))

    assert applied_again == []
    assert not any("CREATE TABLE IF NOT EXISTS poll_task_queue" in sql for sql, _ in conn.executed)
