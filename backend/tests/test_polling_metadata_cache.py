from datetime import datetime, timedelta, timezone


def test_metadata_cache_ttl_expiry_and_refresh_decision():
    from polling.metadata_cache import MetadataCache, MetadataCacheConfig, assess_task_metadata

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache = MetadataCache(MetadataCacheConfig(ttl_seconds=60))
    cache.put("metric", "cpu", {"warning": 80}, version="v1", now=now)

    assert cache.get("metric", "cpu", now=now + timedelta(seconds=30)).value == {"warning": 80}
    assert cache.get("metric", "cpu", now=now + timedelta(seconds=61)).status == "expired"

    decision = assess_task_metadata({"metadata_kind": "metric", "metadata_key": "cpu", "metadata_version": "v1"}, cache, now=now + timedelta(seconds=61))
    assert decision.action == "refresh"
    assert decision.reason == "metadata_expired"


def test_metadata_cache_version_mismatch_defers_instead_of_using_stale_data():
    from polling.metadata_cache import MetadataCache, MetadataCacheConfig, assess_task_metadata

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache = MetadataCache(MetadataCacheConfig(ttl_seconds=300, defer_on_version_mismatch=True))
    cache.put("metric", "cpu", {"warning": 80}, version="v1", now=now)

    decision = assess_task_metadata({"metadata_kind": "metric", "metadata_key": "cpu", "metadata_version": "v2"}, cache, now=now)

    assert decision.action == "defer"
    assert decision.reason == "metadata_version_mismatch"
    assert decision.cache_version == "v1"
    assert decision.task_version == "v2"


def test_metadata_cache_metric_edit_invalidation_removes_entry():
    from polling.metadata_cache import MetadataCache, MetadataCacheConfig

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache = MetadataCache(MetadataCacheConfig(ttl_seconds=300))
    cache.put("metric", "cpu", {"warning": 80}, version="v1", now=now)
    cache.invalidate("metric", "cpu")

    assert cache.get("metric", "cpu", now=now).status == "miss"


def test_metadata_cache_strips_secrets_but_preserves_safe_credential_refs():
    from polling.metadata_cache import MetadataCache, MetadataCacheConfig

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache = MetadataCache(MetadataCacheConfig(ttl_seconds=300))
    cache.put(
        "credential",
        "snmp-prod",
        {
            "credential_ref": "snmp-prod",
            "username": "readonly",
            "password": "secret-password",
            "token": "secret-token",
            "snmp_community": "private",
            "nested": {
                "api_token": "nested-secret",
                "safe_setting": "keep-me",
            },
            "targets": [
                {"ip": "10.0.0.1", "community": "private"},
            ],
        },
        version="v1",
        now=now,
    )

    cached = cache.get("credential", "snmp-prod", now=now).value

    assert cached == {
        "credential_ref": "snmp-prod",
        "username": "readonly",
        "nested": {"safe_setting": "keep-me"},
        "targets": [{"ip": "10.0.0.1"}],
    }


def test_metadata_cache_can_invalidate_all_entries_for_kind():
    from polling.metadata_cache import MetadataCache, MetadataCacheConfig

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    cache = MetadataCache(MetadataCacheConfig(ttl_seconds=300))
    cache.put("ci", "ci-1", {"site": "a"}, version="v1", now=now)
    cache.put("metric", "cpu", {"warning": 80}, version="v1", now=now)

    cache.invalidate_kind("ci")

    assert cache.get("ci", "ci-1", now=now).status == "miss"
    assert cache.get("metric", "cpu", now=now).status == "hit"
