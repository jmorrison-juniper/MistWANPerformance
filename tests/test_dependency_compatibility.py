"""Exercise upgraded dependency boundaries without live services."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import redis

import run_dashboard
from src.api import mist_client
from src.cache import redis_cache
from src.dashboard.app import WANPerformanceDashboard
from src.dashboard.data_provider import DashboardDataProvider
from src.loaders import snowflake_loader
from src.models.dimensions import DimSite
from src.utils.config import MistConfig, OperationalConfig, SnowflakeConfig


@pytest.mark.parametrize("port_count", [0, 1, 1000, 1001])
def test_port_processing_preserves_rates_and_filters_at_parallel_boundary(port_count):
    site = DimSite(site_id="offline-site", site_name="Offline Store")
    port = {
        "device_type": "gateway",
        "port_usage": "wan",
        "port_id": "ge-0/0/0",
        "site_id": site.site_id,
        "mac": "00:00:00:00:00:01",
        "speed": 100,
        "rx_bps": 25_000_000,
        "tx_bps": 50_000_000,
        "rx_bytes": 10**15,
        "tx_bytes": 2 * 10**15,
    }
    circuits, records, down, disabled = run_dashboard.process_port_stats_to_utilization(
        [port.copy() for _ in range(port_count)], {site.site_id: site}, {}
    )
    assert len(circuits) == len(records) == port_count
    assert (down, disabled) == (0, 0)
    assert all(record.utilization_pct == 50.0 for record in records)
    assert all(record.rx_bytes == 10**15 for record in records)


def test_port_processing_ignores_lan_unknown_sites_and_unavailable_links():
    base = {"port_usage": "wan", "port_id": "ge-0/0/0", "site_id": "offline-site"}
    ports = [
        dict(base, port_usage="lan"),
        dict(base, site_id="unknown"),
        dict(base, up=False),
        dict(base, disabled=True),
    ]
    site = DimSite(site_id="offline-site", site_name="Offline Store")
    circuits, records, down, disabled = run_dashboard.process_port_stats_to_utilization(
        ports, {site.site_id: site}, {}
    )
    assert circuits == records == []
    assert (down, disabled) == (1, 1)


@pytest.mark.parametrize("endpoint", ["/", "/_dash-layout", "/_dash-dependencies"])
def test_dash_flask_serves_real_layout_and_callbacks(endpoint):
    dashboard = WANPerformanceDashboard(data_provider=DashboardDataProvider([], []))
    response = dashboard.app.server.test_client().get(endpoint)
    assert response.status_code == 200
    if endpoint == "/_dash-layout":
        assert response.is_json
        assert "props" in response.get_json()
    elif endpoint == "/_dash-dependencies":
        assert len(response.get_json()) > 0
    else:
        assert b"_dash-config" in response.data


def test_wsgi_factory_serves_dashboard_without_starting_live_workers(monkeypatch):
    config = SimpleNamespace(redis=SimpleNamespace(enabled=False), mist=None)
    monkeypatch.setattr("src.utils.config.Config", lambda: config)
    monkeypatch.setattr(run_dashboard, "setup_logging", Mock())
    for name in ["_dashboard_app", "_data_provider", "_cache"]:
        monkeypatch.setattr(run_dashboard, name, None)
    workers = Mock()
    monkeypatch.setattr(run_dashboard, "_start_background_workers", workers)
    server = run_dashboard.create_wsgi_app()
    assert server.test_client().get("/_dash-layout").status_code == 200
    workers.assert_not_called()


@pytest.fixture
def cache(monkeypatch):
    client = Mock()
    monkeypatch.setattr(redis_cache.redis, "from_url", Mock(return_value=client))
    instance = redis_cache.RedisCache("redis://offline.invalid:6379")
    redis_cache.redis.from_url.assert_called_once_with(
        "redis://offline.invalid:6379", decode_responses=True
    )
    return instance


def test_redis_site_serialization_and_retention(cache):
    sites = [{"id": "offline-site", "name": "Store", "latitude": None}]
    assert cache.set_sites(sites)
    key, retention, payload = cache.client.setex.call_args.args
    assert retention == 31 * 24 * 3600
    assert json.loads(payload) == sites
    cache.client.get.return_value = payload
    assert cache.get_sites() == sites
    cache.client.get.assert_called_with(key)


@pytest.mark.parametrize("payload", [None, "invalid-json"])
def test_redis_missing_or_corrupt_site_cache_returns_none(cache, payload):
    cache.client.get.return_value = payload
    assert cache.get_sites() is None


def test_redis_disconnect_and_write_failure_are_reported(cache):
    cache.client.ping.side_effect = redis.ConnectionError("offline failure")
    cache.client.setex.side_effect = redis.ConnectionError("offline failure")
    assert not cache.is_connected()
    assert not cache.set_sites([])


@pytest.fixture
def warehouse(monkeypatch):
    connection = Mock()
    monkeypatch.setattr(
        snowflake_loader.snowflake_connector, "connect", Mock(return_value=connection)
    )
    config = SnowflakeConfig(account="offline", user="fixture", password="not-a-secret")
    manager = snowflake_loader.SnowflakeConnection(config)
    manager.connect()
    return manager


def test_snowflake_preserves_parameter_binding_and_closes_cursor(warehouse):
    cursor = warehouse.connection.cursor.return_value
    cursor.fetchall.return_value = [{"VALUE": 12.5}]
    assert warehouse.execute("SELECT %(value)s", {"value": 12.5}) == [{"VALUE": 12.5}]
    cursor.execute.assert_called_once_with("SELECT %(value)s", {"value": 12.5})
    cursor.close.assert_called_once()


def test_snowflake_failed_query_closes_cursor_without_committing(warehouse):
    cursor = warehouse.connection.cursor.return_value
    cursor.execute.side_effect = RuntimeError("offline query failure")
    with pytest.raises(RuntimeError, match="offline query failure"):
        warehouse.execute("SELECT 1")
    cursor.close.assert_called_once()
    warehouse.connection.commit.assert_not_called()


def test_snowflake_empty_batch_and_disconnected_operations(warehouse):
    warehouse.connection.reset_mock()
    assert warehouse.execute_many("INSERT", []) == 0
    warehouse.connection.cursor.assert_not_called()
    warehouse.disconnect()
    with pytest.raises(RuntimeError, match="Not connected"):
        warehouse.execute("SELECT 1")


def test_mist_sdk_site_pagination_and_session_contract(monkeypatch):
    session = Mock()
    session_factory = Mock(return_value=session)
    monkeypatch.setattr(mist_client, "APISession", session_factory)
    connection = mist_client.MistConnection(
        MistConfig(api_token="offline-fixture", org_id="offline-org"),
        OperationalConfig(rate_limit_delay=0, retry_delay=0),
    )
    first_page = [{"id": f"site-{index}"} for index in range(1000)]
    sdk_call = Mock(
        side_effect=[SimpleNamespace(data=first_page), SimpleNamespace(data=[{"id": "last"}])]
    )
    monkeypatch.setattr(mist_client.mistapi.api.v1.orgs.sites, "listOrgSites", sdk_call)
    result = mist_client.MistSiteOperations(connection).get_sites()
    assert len(result) == 1001
    assert result[-1] == {"id": "last"}
    assert [call.kwargs["page"] for call in sdk_call.call_args_list] == [1, 2]
    session_factory.assert_called_once_with(host="api.mist.com", apitoken="offline-fixture")
