from dash.development.base_component import Component

from src.dashboard.data_provider import DashboardDataProvider
from src.dashboard.app import WANPerformanceDashboard
from src.dashboard.pages.detail_data import (
    shape_gateway_detail,
    shape_port_detail,
    shape_vpn_peer_detail,
)

SITE_ID = "11111111-1111-1111-1111-111111111111"
GATEWAY_ID = "gw-1"
GATEWAY_MAC = "aa:bb:cc:dd:ee:ff"
PORT_ID = "ge-0/0/1"
PEER_ID = "11:22:33:44:55:66"


class FakeProvider:
    site_lookup = {SITE_ID: "Store 100"}
    sites = [{"id": SITE_ID, "name": "Store 100"}]
    gateways = [
        {
            "id": GATEWAY_ID,
            "mac": GATEWAY_MAC,
            "name": "Store 100 Gateway",
            "site_id": SITE_ID,
            "connected": True,
            "last_seen": 1_700_000_000,
            "cpu": 22.5,
            "memory": 44.0,
            "uptime": "12 days",
        }
    ]
    port_stats = [
        {
            "site_id": SITE_ID,
            "mac": GATEWAY_MAC,
            "port_id": PORT_ID,
            "name": "WAN 1",
            "up": True,
            "speed": 1000,
            "rx_bps": 125_000_000,
            "tx_bps": 50_000_000,
            "utilization_pct": 12.5,
            "rx_bytes": 1_500_000,
            "tx_bytes": 2_500_000,
            "rx_packets": 1000,
            "tx_packets": 2000,
            "mtu": 1500,
            "type": "ethernet",
            "port_usage": "wan",
            "provider": "ISP",
            "ip": "192.0.2.10",
            "rx_errors": 1,
            "tx_errors": 2,
            "rx_unicast": 10,
            "tx_unicast": 20,
            "rx_multicast": 30,
            "tx_multicast": 40,
            "rx_broadcast": 50,
            "tx_broadcast": 60,
            "rx_drops": 3,
            "tx_drops": 4,
            "rx_crc": 5,
            "tx_crc": 6,
            "timestamp": 1_700_000_100,
        }
    ]
    vpn_peers = [
        {
            "site_id": SITE_ID,
            "mac": GATEWAY_MAC,
            "peer_mac": PEER_ID,
            "peer_name": "Remote Peer",
            "peer_site_name": "Remote Store",
            "up": True,
            "latency": 33.3,
            "loss": 0.25,
            "jitter": 4.5,
            "mos": 4.2,
            "mtu": 1400,
            "peer_ip": "198.51.100.10",
            "local_ip": "192.0.2.1",
            "path_type": "wan",
            "vpn_name": "corp-vpn",
            "uptime": "3 days",
            "tx_bytes": 1000,
            "rx_bytes": 2000,
            "tx_packets": 10,
            "rx_packets": 20,
            "timestamp": 1_700_000_200,
        }
    ]

    def get_site_vpn_peers(self, site_id):
        return [peer for peer in self.vpn_peers if peer["site_id"] == site_id]

    def get_vpn_peer_table_data(self, site_id=None):
        return []

    def get_gateway_port_timeseries(self, **kwargs):
        return [
            {"timestamp": 1_700_000_000, "rx_bps": 100_000_000, "tx_bps": 40_000_000},
            {"timestamp": 1_700_003_600, "rx_bps": 120_000_000, "tx_bps": 45_000_000},
        ]

    def get_device_metrics_timeseries(self, **kwargs):
        metric = kwargs["metric"]
        return [
            {"timestamp": 1_700_000_000, "value": 20 if metric == "cpu" else 40},
            {"timestamp": 1_700_003_600, "value": 25 if metric == "cpu" else 45},
        ]

    def get_vpn_peer_timeseries(self, **kwargs):
        return [
            {"timestamp": 1_700_000_000, "loss": 0.1, "latency": 30, "jitter": 4},
            {"timestamp": 1_700_003_600, "loss": 0.2, "latency": 35, "jitter": 5},
        ]


class RaisingProvider(FakeProvider):
    @property
    def gateways(self):
        raise RuntimeError("boom")


class PortRaisingProvider(FakeProvider):
    @property
    def port_stats(self):
        raise RuntimeError("boom")


class VPNRaisingProvider(FakeProvider):
    @property
    def vpn_peers(self):
        raise RuntimeError("boom")


class StubRedisCache:
    def __init__(self, ports=None, peers=None):
        self.ports = ports or []
        self.peers = peers or []

    def get_site_port_stats(self, site_id):
        return {"port_stats": [port for port in self.ports if port.get("site_id") == site_id]}

    def get_all_site_port_stats(self, site_ids):
        return [port for port in self.ports if port.get("site_id") in site_ids]

    def get_site_vpn_peers(self, site_id):
        return [peer for peer in self.peers if peer.get("site_id") == site_id]

    def get_gateway_port_timeseries(self, *args, **kwargs):
        return []

    def get_vpn_peer_timeseries(self, *args, **kwargs):
        return []

    def get_device_metrics_timeseries(self, *args, **kwargs):
        return []


def _real_provider(peer_id=PEER_ID):
    provider = DashboardDataProvider(sites=[], circuits=[])
    provider.site_lookup = {SITE_ID: "Store 100"}
    provider.update_gateway_inventory(
        {
            "total": 1,
            "connected": 1,
            "disconnected": 0,
            "gateways": [
                {
                    "id": GATEWAY_ID,
                    "mac": GATEWAY_MAC,
                    "name": "Store 100 Gateway",
                    "site_id": SITE_ID,
                    "connected": True,
                    "last_seen": 1_700_000_000,
                }
            ],
        }
    )
    provider.redis_cache = StubRedisCache(
        ports=[
            {
                "site_id": SITE_ID,
                "mac": GATEWAY_MAC,
                "port_id": PORT_ID,
                "name": "WAN 1",
                "up": True,
                "speed": 1000,
            }
        ],
        peers=[
            {
                "site_id": SITE_ID,
                "mac": GATEWAY_MAC,
                "peer_mac": peer_id,
                "peer_router_name": "Remote Peer",
                "up": True,
                "latency": 10,
                "loss": 0,
                "jitter": 1,
                "mos": 4.5,
            }
        ],
    )
    return provider


def _figure_trace_count(figure):
    return len(figure.to_plotly_json().get("data", []))


def test_gateway_detail_populated_data():
    detail = shape_gateway_detail(FakeProvider(), {"gateway_id": GATEWAY_ID, "site_id": SITE_ID})

    assert detail["gateway_name"] == "Store 100 Gateway"
    assert detail["site_name"] == "Store 100"
    assert detail["status"] == "Up"
    assert detail["ports_up"] == "1"
    assert detail["vpn_peers"] == "1"
    assert detail["wan_ports"][0]["port_name"].startswith("[WAN 1]")
    assert detail["vpn_peer_rows"][0]["peer_name"].startswith("[Remote Peer]")
    assert _figure_trace_count(detail["bandwidth_figure"]) == 2
    assert _figure_trace_count(detail["device_metrics_figure"]) == 2


def test_gateway_detail_missing_and_raising_data():
    missing = shape_gateway_detail(FakeProvider(), {"gateway_id": "unknown", "site_id": SITE_ID})
    failing = shape_gateway_detail(
        RaisingProvider(), {"gateway_id": GATEWAY_ID, "site_id": SITE_ID}
    )

    assert missing["status"] == "Unknown"
    assert missing["wan_ports"] == []
    assert failing["status"] == "Unknown"
    assert failing["last_seen"] == "Unable to load gateway data"
    assert failing["wan_ports"] == []


def test_port_detail_populated_data():
    detail = shape_port_detail(
        FakeProvider(), {"site_id": SITE_ID, "port_id": PORT_ID, "gateway_id": GATEWAY_ID}
    )

    assert detail["port_name"] == "WAN 1"
    assert detail["site_name"] == "Store 100"
    assert detail["status"] == "Up"
    assert detail["rx_mbps"] == "125.0"
    assert detail["tx_mbps"] == "50.0"
    assert detail["util_pct"] == "12.5"
    assert detail["mtu"] == "1,500"
    assert detail["rx_err_count"] == "1"
    assert detail["tx_crc"] == "6"
    assert _figure_trace_count(detail["bandwidth_figure"]) == 2


def test_port_detail_missing_and_raising_data():
    missing = shape_port_detail(FakeProvider(), {"site_id": SITE_ID, "port_id": "missing"})
    failing = shape_port_detail(PortRaisingProvider(), {"site_id": SITE_ID, "port_id": PORT_ID})

    assert missing["status"] == "No data for this port yet"
    assert missing["bandwidth_figure"].to_plotly_json()["layout"]["annotations"][0]["text"]
    assert failing["status"] == "Unable to load port data"


def test_vpn_peer_detail_populated_data():
    detail = shape_vpn_peer_detail(FakeProvider(), {"site_id": SITE_ID, "peer_id": PEER_ID})

    assert detail["peer_name"] == "Remote Peer"
    assert detail["local_site"] == "Store 100"
    assert detail["remote_site"] == "Remote Store"
    assert detail["status"] == "Up"
    assert detail["loss_pct"] == "0.25"
    assert detail["latency_ms"] == "33.3"
    assert detail["mos_score"] == "4.20"
    assert detail["peer_mac"] == PEER_ID
    assert detail["tunnel_name"] == "corp-vpn"
    assert _figure_trace_count(detail["quality_figure"]) == 3


def test_vpn_peer_detail_missing_and_raising_data():
    missing = shape_vpn_peer_detail(FakeProvider(), {"site_id": SITE_ID, "peer_id": "missing"})
    failing = shape_vpn_peer_detail(VPNRaisingProvider(), {"site_id": SITE_ID, "peer_id": PEER_ID})

    assert missing["status"] == "No data for this VPN peer yet"
    assert missing["peer_mac"] == "-"
    assert failing["status"] == "Unable to load VPN peer data"


def test_real_provider_gateway_inventory_finds_gateway_by_id_and_mac():
    provider = _real_provider()

    by_id = shape_gateway_detail(provider, {"gateway_id": GATEWAY_ID, "site_id": SITE_ID})
    by_mac = shape_gateway_detail(provider, {"gateway_id": GATEWAY_MAC, "site_id": SITE_ID})

    assert by_id["gateway_name"] == "Store 100 Gateway"
    assert by_id["status"] == "Up"
    assert by_mac["gateway_name"] == "Store 100 Gateway"
    assert by_mac["status"] == "Up"


def test_real_provider_unknown_gateway_is_unknown_not_down():
    provider = _real_provider()

    detail = shape_gateway_detail(provider, {"gateway_id": "unknown", "site_id": SITE_ID})

    assert detail["status"] == "Unknown"
    assert detail["status_class"] == "badge bg-secondary"
    assert detail["status"] != "Down"


def test_real_provider_gateway_peers_do_not_duplicate_when_table_rows_exist():
    provider = _real_provider()
    provider.get_vpn_peer_table_data = lambda site_id=None: [
        {
            "site_name": "Store 100",
            "vpn_name": "corp vpn",
            "peer_router_name": "Remote Peer",
            "peer_port_id": "wan",
            "port_id": PORT_ID,
            "status": "Up",
            "latency_ms": 10,
            "loss_pct": 0,
            "jitter_ms": 1,
            "mos": 4.5,
        }
    ]

    detail = shape_gateway_detail(provider, {"gateway_id": GATEWAY_ID, "site_id": SITE_ID})

    assert detail["vpn_peers"] == "1"
    assert len(detail["vpn_peer_rows"]) == 1


def test_real_provider_gateway_peer_link_encodes_peer_id():
    peer_id = "peer with space)"
    provider = _real_provider(peer_id=peer_id)

    detail = shape_gateway_detail(provider, {"gateway_id": GATEWAY_ID, "site_id": SITE_ID})

    assert f"/vpn/{SITE_ID}/peer%20with%20space%29" in detail["vpn_peer_rows"][0]["peer_name"]


def _walk_ids(component):
    ids = []
    if isinstance(component, Component):
        component_id = getattr(component, "id", None)
        if component_id is not None:
            ids.append(component_id)
        children = getattr(component, "children", None)
        if isinstance(children, (list, tuple)):
            for child in children:
                ids.extend(_walk_ids(child))
        elif children is not None:
            ids.extend(_walk_ids(children))
    elif isinstance(component, (list, tuple)):
        for child in component:
            ids.extend(_walk_ids(child))
    return ids


def test_page_layouts_do_not_duplicate_ids_and_vpn_detail_chart_is_unique():
    dashboard = WANPerformanceDashboard(app_name="test", data_provider=FakeProvider())
    layouts = [
        dashboard._build_overview_layout(),
        dashboard._build_gateway_page(GATEWAY_ID, SITE_ID),
        dashboard._build_port_page(SITE_ID, PORT_ID, GATEWAY_ID),
        dashboard._build_vpn_peer_page(SITE_ID, PEER_ID),
    ]

    for layout in layouts:
        ids = _walk_ids(layout)
        assert len(ids) == len(set(ids))

    vpn_ids = set(_walk_ids(layouts[-1]))
    assert "vpn-peer-quality-chart" in vpn_ids
    assert "vpn-quality-chart" not in vpn_ids
