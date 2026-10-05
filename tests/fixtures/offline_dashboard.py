"""Launch the real dashboard with synthetic fixtures and no service clients."""

from copy import deepcopy
from pathlib import Path

from flask import send_file

from src.dashboard.app import WANPerformanceDashboard
from src.dashboard.data_provider import DashboardDataProvider
from src.models.dimensions import DimCircuit, DimSite
from src.models.facts import CircuitUtilizationRecord
from tests.test_detail_pages import GATEWAY_MAC, PORT_ID, SITE_ID, FakeProvider


class OfflineProvider(DashboardDataProvider):
    """Use the tested detail fixtures alongside the real overview calculations."""

    def __init__(self):
        site = DimSite(site_id=SITE_ID, site_name="Store 100 (synthetic)", region="Demo")
        circuit = DimCircuit(
            circuit_id=f"{GATEWAY_MAC}:{PORT_ID}",
            site_id=SITE_ID,
            device_id=GATEWAY_MAC,
            port_name=PORT_ID,
            bandwidth_mbps=1000,
        )
        super().__init__(sites=[site], circuits=[circuit])
        self.gateways = deepcopy(FakeProvider.gateways)
        self.port_stats = deepcopy(FakeProvider.port_stats)
        self.vpn_peers = deepcopy(FakeProvider.vpn_peers)
        self.redis_cache = None
        self.gateways_total, self.gateways_connected = 1, 1
        self.data_load_complete = True
        self.update_utilization(
            [
                CircuitUtilizationRecord(
                    site_id=SITE_ID,
                    circuit_id=circuit.circuit_id,
                    hour_key="2023101422",
                    utilization_pct=12.5,
                    rx_bytes=1_500_000,
                    tx_bytes=2_500_000,
                    bandwidth_mbps=1000,
                )
            ]
        )

    def get_site_vpn_peers(self, site_id):
        return [peer for peer in self.vpn_peers if peer["site_id"] == site_id]

    def get_gateway_port_timeseries(self, *_args, **kwargs):
        return FakeProvider().get_gateway_port_timeseries(**kwargs)

    def get_device_metrics_timeseries(self, *_args, **kwargs):
        return FakeProvider().get_device_metrics_timeseries(**kwargs)

    def get_vpn_peer_timeseries(self, *_args, **kwargs):
        return FakeProvider().get_vpn_peer_timeseries(**kwargs)


class OfflineDashboard:
    """Build and run an isolated fixture-backed instance of the production UI."""

    @staticmethod
    def build():
        dashboard = WANPerformanceDashboard(
            app_name="WAN Performance - OFFLINE SYNTHETIC DATA", data_provider=OfflineProvider()
        )
        dashboard.app.config.external_stylesheets = []
        stylesheet = Path("data/cache/offline-assets/darkly.css").resolve()
        if stylesheet.is_file():
            dashboard.app.server.add_url_rule(
                "/offline-theme.css", "offline-theme", lambda: send_file(stylesheet)
            )
            dashboard.app.config.external_stylesheets = ["/offline-theme.css"]
        return dashboard

    @classmethod
    def run(cls):
        # SECURITY: Loopback only; this preview never constructs service clients.
        cls.build().run(host="127.0.0.1", port=8051, debug=False)


if __name__ == "__main__":
    OfflineDashboard.run()
