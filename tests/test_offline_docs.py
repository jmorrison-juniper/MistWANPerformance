"""Guard the concise introduction and service-free screenshot preview."""

import re
from pathlib import Path

import pytest

from src.dashboard.pages.detail_data import (
    shape_gateway_detail,
    shape_port_detail,
    shape_vpn_peer_detail,
)
from tests.fixtures.offline_dashboard import OfflineDashboard
from tests.test_detail_pages import PEER_ID, PORT_ID, SITE_ID

ROOT = Path(__file__).resolve().parents[1]


class TestOfflineDocumentation:
    def test_readme_has_only_six_questions(self):
        readme = (ROOT / "README.md").read_text()
        assert re.findall(r"^## (.+)$", readme, re.MULTILINE) == [
            "What",
            "How",
            "Where",
            "When",
            "Why",
            "Who",
        ]
        assert not re.search(r"^### ", readme, re.MULTILINE)

    @pytest.mark.parametrize("document", ["README.md", "docs/screens.md", "docs/changelog.md"])
    def test_local_documentation_links_exist(self, document):
        path = ROOT / document
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if not target.startswith(("https://", "http://", "#")):
                assert (path.parent / target.split("#")[0]).exists(), target

    @pytest.mark.parametrize("screen", ["overview", "gateway", "port", "vpn-peer"])
    def test_screenshots_are_png_images(self, screen):
        image = (ROOT / "docs/screenshots" / f"{screen}.png").read_bytes()
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(image) > 10_000

    def test_offline_app_serves_layout_and_populated_details(self):
        dashboard = OfflineDashboard.build()
        client = dashboard.app.server.test_client()
        assert client.get("/").status_code == 200
        assert client.get("/_dash-layout").status_code == 200
        provider = dashboard.data_provider
        assert provider.redis_cache is None
        assert not hasattr(provider, "api_client")
        gateway = shape_gateway_detail(provider, {"gateway_id": "aabbccddeeff", "site_id": SITE_ID})
        port = shape_port_detail(provider, {"port_id": PORT_ID, "site_id": SITE_ID})
        peer = shape_vpn_peer_detail(provider, {"peer_id": PEER_ID, "site_id": SITE_ID})
        assert gateway["gateway_name"] == "Store 100 Gateway"
        assert port["rx_mbps"] == "125.0"
        assert peer["latency_ms"] == "33.3"
