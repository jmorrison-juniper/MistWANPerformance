"""
MistWANPerformance Dashboard Pages

Multi-page dashboard architecture with dedicated pages for:
- Overview: Main dashboard with site/circuit summaries
- Gateway: Gateway-specific metrics and device details
- Port: WAN port statistics and time-series data
- VPN Peer: VPN peer path quality metrics and trends
"""

from src.dashboard.pages.overview import OverviewPage
from src.dashboard.pages.gateway import GatewayPage
from src.dashboard.pages.port import PortPage
from src.dashboard.pages.vpn_peer import VPNPeerPage

__all__ = ["OverviewPage", "GatewayPage", "PortPage", "VPNPeerPage"]
