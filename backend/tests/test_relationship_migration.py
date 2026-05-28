from services.relationship_migration import LEGACY_RELATIONSHIP_TYPE_MAP, audit_relationship_type_counts, migrate_relationship_types


class FakeResult:
    def __init__(self, records=None, single_record=None):
        self.records = records or []
        self.single_record = single_record

    def __iter__(self):
        return iter(self.records)

    def single(self):
        return self.single_record


class FakeSession:
    def __init__(self):
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        if "RETURN type(r) AS type" in query:
            return FakeResult([{"type": "CONNECTED_TO", "count": 2}, {"type": "CONNECTS_TO", "count": 1}])
        if "legacy_count" in query:
            return FakeResult(single_record={"legacy_count": 2, "duplicate_count": 1, "create_count": 1})
        if "deleted_count" in query:
            return FakeResult(single_record={"deleted_count": 2})
        return FakeResult()


def test_audit_relationship_type_counts_is_read_only():
    session = FakeSession()
    assert audit_relationship_type_counts(session) == {"CONNECTED_TO": 2, "CONNECTS_TO": 1}
    assert "DELETE" not in session.calls[0][0]
    assert "CREATE" not in session.calls[0][0]


def test_migrate_relationship_types_dry_run_does_not_mutate():
    session = FakeSession()
    report = migrate_relationship_types(session, LEGACY_RELATIONSHIP_TYPE_MAP, apply=False)
    entry = report["mappings"][0]
    assert report["mode"] == "dry-run"
    assert (entry["from"], entry["to"], entry["planned_creates"], entry["skipped_duplicates"]) == ("CONNECTED_TO", "CONNECTS_TO", 1, 1)
    assert report["after"] == report["before"]
    assert report["after_if_applied"] == {"CONNECTED_TO": 0, "CONNECTS_TO": 2}
    assert all("DELETE" not in query and "CREATE" not in query for query, _ in session.calls)


def test_migrate_relationship_types_rejects_unsafe_legacy_type():
    session = FakeSession()
    try:
        migrate_relationship_types(session, {"CONNECTED_TO`) DELETE r //": "CONNECTS_TO"}, apply=False)
    except ValueError:
        return
    raise AssertionError("unsafe legacy relationship type was accepted")


def test_migrate_relationship_types_apply_copies_properties_and_deletes_after_replacement():
    session = FakeSession()
    report = migrate_relationship_types(session, LEGACY_RELATIONSHIP_TYPE_MAP, apply=True)
    apply_query = session.calls[-2][0]
    assert report["mode"] == "apply"
    assert report["mappings"][0]["deleted_legacy"] == 2
    assert "CREATE (a)-[new_rel:CONNECTS_TO]->(b)" in apply_query
    assert "SET new_rel = props" in apply_query
    assert "MATCH (a)-[replacement:CONNECTS_TO]->(b)" in apply_query
    assert "DELETE old_rel" in apply_query
