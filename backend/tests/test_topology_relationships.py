import asyncio
from unittest.mock import patch

from repositories import topology_repo
from models.user import User
from routers.links import CiIdsPayload, get_cis_relationships
from services import link_service


def test_create_link_rejects_legacy_connected_to(mock_neo4j_driver):
    try:
        topology_repo.create_link("ci-a", "ci-b", "CONNECTED_TO")
    except ValueError:
        return
    raise AssertionError("legacy CONNECTED_TO relationship was accepted")


def test_create_link_accepts_connects_to(mock_neo4j_driver):
    topology_repo.create_link("ci-a", "ci-b", "CONNECTS_TO")

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    assert "MERGE (a)-[r:CONNECTS_TO]->(b)" in query


def test_get_links_query_includes_hosted_on(mock_neo4j_driver):
    mock_neo4j_driver.mock_session.set_default_response([])

    topology_repo.get_links(allowed_locations=[], is_admin=True)

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    assert "HOSTED_ON" in query
    assert "CONNECTS_TO" in query
    assert "DEPENDS_ON" in query
    assert "CONNECTED_TO" not in query


def test_cis_relationships_route_uses_scoped_service_path():
    async def run_route():
        user = User(
            username="operator",
            role="OPERATOR",
            permissions=["CI_VIEW"],
            allowed_locations=["HQ-Madrid"],
        )
        with patch("routers.links.link_service.get_cis_relationships", return_value={"ci-a": {}}) as mock_service:
            result = await get_cis_relationships(CiIdsPayload(ci_ids=["ci-a"]), user)
        return result, mock_service

    result, mock_service = asyncio.run(run_route())
    assert result == {"ci-a": {}}
    mock_service.assert_called_once()
    assert mock_service.call_args.args[0] == ["ci-a"]
    assert mock_service.call_args.args[1].allowed_locations == ["HQ-Madrid"]


def test_cis_relationship_summary_applies_non_admin_location_scope(mock_neo4j_driver):
    mock_neo4j_driver.mock_session.set_default_response([])
    user = User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=["HQ-Madrid"],
    )

    link_service.get_cis_relationships(["ci-a", "ci-b"], user)

    query_call = mock_neo4j_driver.mock_session.queries[-1]
    assert "a.id IN $ci_ids AND a.location_name IN $allowed_locations" in query_call["query"]
    assert "b.id IN $ci_ids AND b.location_name IN $allowed_locations" in query_call["query"]
    assert query_call["params"]["allowed_locations"] == ["HQ-Madrid"]


def test_cis_relationship_summary_does_not_populate_disallowed_requested_ci(mock_neo4j_driver):
    mock_neo4j_driver.mock_session.set_default_response([
        {
            "source_id": "allowed-ci",
            "source_label": "Allowed CI",
            "source_location": "HQ-Madrid",
            "target_id": "blocked-ci",
            "target_label": "Blocked CI",
            "target_location": "Secret",
            "rel_type": "CONNECTS_TO",
        }
    ])
    user = User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=["HQ-Madrid"],
    )

    summary = link_service.get_cis_relationships(["allowed-ci", "blocked-ci"], user)

    assert summary["allowed-ci"]["asSource"] == [
        {"otherId": "blocked-ci", "otherLabel": "Blocked CI", "type": "CONNECTS_TO"}
    ]
    assert summary["blocked-ci"] == {"asSource": [], "asTarget": []}


def test_cis_relationship_summary_returns_empty_scoped_summary_without_locations(mock_neo4j_driver):
    user = User(
        username="operator",
        role="OPERATOR",
        permissions=["CI_VIEW"],
        allowed_locations=[],
    )

    summary = link_service.get_cis_relationships(["ci-a"], user)

    assert summary == {"ci-a": {"asSource": [], "asTarget": []}}
    assert mock_neo4j_driver.mock_session.queries == []


# ---------------------------------------------------------------------------
# Slice 1 (feat-324) — tunnel medium + hub-obligatorio validation
# ---------------------------------------------------------------------------


def test_link_model_accepts_medium():
    """Slice 1 / VPN-Rel R2 / Sc 4: Link.medium is a Literal['vpn','sd_wan','satellite']."""
    from models.core import Link

    link = Link(
        source="hub-a", target="router-b", relationship="CONNECTS_TO", medium="vpn"
    )
    assert link.medium == "vpn"


def test_link_model_accepts_satellite_medium():
    """Slice 1 / VPN-Rel R2 / Sc 4: 'satellite' is also a valid medium."""
    from models.core import Link

    link = Link(
        source="hub-a",
        target="router-b",
        relationship="CONNECTS_TO",
        medium="satellite",
    )
    assert link.medium == "satellite"


def test_link_model_medium_is_optional():
    """Slice 1 / VPN-Rel R4 / Sc 8: medium is optional on legacy links."""
    from models.core import Link

    link = Link(source="a", target="b", relationship="CONNECTS_TO")
    assert link.medium is None


def test_create_link_persists_medium(mock_neo4j_driver):
    """Slice 1 / VPN-Rel R2 / Sc 4: topology_repo.create_link passes medium
    through the relationship properties."""
    topology_repo.create_link("hub-a", "router-b", "CONNECTS_TO", medium="vpn")

    query = mock_neo4j_driver.mock_session.queries[-1]["query"]
    params = mock_neo4j_driver.mock_session.queries[-1]["params"]
    assert "r.medium = $medium" in query
    assert params["medium"] == "vpn"


def test_get_links_returns_medium_in_payload(mock_neo4j_driver):
    """Slice 1 / VPN-Rel R4 / Sc 8: topology_repo.get_links returns medium when set."""
    mock_neo4j_driver.mock_session.set_default_response([
        {
            "s": "hub-a",
            "sl": "Hub-A",
            "t": "router-b",
            "tl": "Router-B",
            "rel": "CONNECTS_TO",
            "medium": "vpn",
        }
    ])

    links = topology_repo.get_links(allowed_locations=[], is_admin=True)

    assert links == [
        {
            "source": "hub-a",
            "source_label": "Hub-A",
            "target": "router-b",
            "target_label": "Router-B",
            "relationship": "CONNECTS_TO",
            "medium": "vpn",
        }
    ]


def test_get_links_omits_medium_when_unset(mock_neo4j_driver):
    """Slice 1 / VPN-Rel R4 / Sc 8: legacy links without medium expose no medium key
    so existing consumers stay unchanged."""
    mock_neo4j_driver.mock_session.set_default_response([
        {
            "s": "hub-a",
            "sl": "Hub-A",
            "t": "router-b",
            "tl": "Router-B",
            "rel": "CONNECTS_TO",
            "medium": None,
        }
    ])

    links = topology_repo.get_links(allowed_locations=[], is_admin=True)

    assert "medium" not in links[0]


def test_validate_tunnel_endpoint_hub_accepts_hub_to_remote(mock_neo4j_driver):
    """Slice 1 / VPN-Rel R3 / Sc 6: a tunnel relation whose source is a vpn_hub is
    accepted by the validation helper."""
    from services.link_service import validate_tunnel_endpoint_hub

    # Validate against a hub endpoint: returns without raising.
    validate_tunnel_endpoint_hub(
        source_id="hub-a",
        source_type="vpn_hub",
        target_id="router-b",
        target_type="router",
        medium="vpn",
    )


def test_validate_tunnel_endpoint_hub_rejects_non_hub():
    """Slice 1 / VPN-Rel R3 / Sc 7: a tunnel relation with no vpn_hub endpoint
    raises HTTPException(400) without partial persistence."""
    from fastapi import HTTPException
    from services.link_service import validate_tunnel_endpoint_hub

    raised = False
    try:
        validate_tunnel_endpoint_hub(
            source_id="router-a",
            source_type="router",
            target_id="router-b",
            target_type="router",
            medium="vpn",
        )
    except HTTPException as exc:
        raised = exc.status_code == 400
    assert raised, "expected HTTP 400 when neither endpoint is vpn_hub"


def test_validate_tunnel_endpoint_hub_rejects_unsupported_medium():
    """Slice 1 / VPN-Rel R2 / Sc 5: unsupported medium values are rejected."""
    from fastapi import HTTPException
    from services.link_service import validate_tunnel_endpoint_hub

    raised = False
    try:
        validate_tunnel_endpoint_hub(
            source_id="hub-a",
            source_type="vpn_hub",
            target_id="router-b",
            target_type="router",
            medium="microwave",
        )
    except HTTPException as exc:
        raised = exc.status_code == 400
    assert raised, "expected HTTP 400 for unsupported medium"


def test_validate_tunnel_endpoint_hub_skips_when_no_medium():
    """Slice 1 / VPN-Rel R2: a non-tunnel relation is not subject to the hub rule."""
    from services.link_service import validate_tunnel_endpoint_hub

    # No medium → no-op; should not raise even when neither endpoint is a hub.
    validate_tunnel_endpoint_hub(
        source_id="router-a",
        source_type="router",
        target_id="router-b",
        target_type="router",
        medium=None,
    )


def test_validate_tunnel_endpoint_hub_requires_existing_endpoint_types(mock_neo4j_driver):
    """Slice 1 / VPN-Rel R3 / Sc 7: when neither endpoint is a known vpn_hub,
    the validator fetches each endpoint's type from the repository and rejects."""
    from fastapi import HTTPException
    from services.link_service import validate_tunnel_endpoint_hub

    mock_neo4j_driver.mock_session.set_default_response([
        {"layer": "router"},
    ])

    raised = False
    try:
        validate_tunnel_endpoint_hub(
            source_id="router-a",
            source_type=None,
            target_id="router-b",
            target_type=None,
            medium="vpn",
        )
    except HTTPException as exc:
        raised = exc.status_code == 400
    assert raised, "expected HTTP 400 when both endpoints resolve to non-hub layers"


def test_create_link_service_runs_hub_validation(mock_neo4j_driver):
    """Slice 1 / VPN-Rel R3 / Sc 7: link_service.create_link rejects tunnel
    relations with no vpn_hub endpoint."""
    from fastapi import HTTPException
    from models.core import Link
    from services import link_service

    # Stub out the repository so we can observe whether hub validation runs.
    captured = {}

    def fake_create_link(*args, **kwargs):
        captured["called"] = True

    mock_neo4j_driver.mock_session.set_default_response([
        {"layer": "router"},
    ])
    with patch.object(link_service.topology_repo, "create_link", fake_create_link):
        raised = False
        try:
            link_service.create_link(
                Link(
                    source="router-a",
                    target="router-b",
                    relationship="CONNECTS_TO",
                    medium="vpn",
                )
            )
        except HTTPException as exc:
            raised = exc.status_code == 400
        assert raised, "expected HTTP 400 from hub-rule validation"
    assert "called" not in captured, "repository must not be touched on validation failure"
