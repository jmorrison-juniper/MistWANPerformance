"""
MistWANPerformance Dashboard - Gateway Detail Page

Dedicated page for viewing detailed gateway information including:
- Gateway status and health metrics
- WAN port list with clickable links
- VPN peer connections
- Device metrics time-series
- CPU/Memory utilization
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

from dash import dcc, html, dash_table, callback, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.dashboard.pages.shared import (
    COLORS,
    REFRESH_INTERVAL_MS,
    NavigationBar,
    StatusCards,
    ChartBuilders,
    LinkBuilder,
)

logger = logging.getLogger(__name__)


class GatewayPage:
    """
    Gateway detail page showing device-specific information.

    URL Pattern: /gateway/<gateway_id>?site_id=<site_id>

    Displays:
    - Gateway identification and status
    - WAN ports table (clickable to port detail)
    - VPN peers table (clickable to peer detail)
    - Device metrics (CPU, memory, uptime)
    - Bandwidth time-series for all ports
    """

    PAGE_ID = "gateway-page"

    def __init__(self, data_provider: Optional[Any] = None):
        """
        Initialize gateway page.

        Args:
            data_provider: Data provider instance for live data
        """
        self.data_provider = data_provider

    def build_layout(
        self, gateway_id: str, site_id: Optional[str] = None, data_provider: Optional[Any] = None
    ) -> html.Div:
        """
        Build the gateway detail page layout.

        Args:
            gateway_id: Gateway device ID from URL
            site_id: Optional site ID from query string
            data_provider: Optional data provider (overrides instance provider)

        Returns:
            Complete page layout
        """
        # Use provided data_provider or fall back to instance provider
        if data_provider is not None:
            self.data_provider = data_provider
        breadcrumbs = [{"label": "Gateway Details", "href": None}]

        return html.Div(
            [
                # Store gateway context
                dcc.Store(
                    id="gateway-context", data={"gateway_id": gateway_id, "site_id": site_id}
                ),
                # Navigation bar
                NavigationBar.build("Gateway Details", breadcrumbs),
                # Main container
                dbc.Container(
                    [
                        # Header with gateway info
                        self._build_header(gateway_id),
                        # Status cards row
                        self._build_status_row(),
                        # Main content
                        dbc.Row(
                            [
                                # Left column - WAN Ports
                                dbc.Col([self._build_wan_ports_card()], width=6),
                                # Right column - VPN Peers
                                dbc.Col([self._build_vpn_peers_card()], width=6),
                            ],
                            className="mb-4",
                        ),
                        # Device metrics charts
                        dbc.Row(
                            [
                                dbc.Col([self._build_bandwidth_chart_card()], width=6),
                                dbc.Col([self._build_device_metrics_card()], width=6),
                            ]
                        ),
                        # Refresh interval
                        dcc.Interval(
                            id="gateway-refresh-interval",
                            interval=REFRESH_INTERVAL_MS,
                            n_intervals=0,
                        ),
                    ],
                    fluid=True,
                ),
            ],
            id=self.PAGE_ID,
        )

    def _build_header(self, gateway_id: str) -> dbc.Row:
        """Build the page header with gateway identification."""
        return dbc.Row(
            [
                dbc.Col(
                    [
                        html.H2(
                            [
                                html.Span("Gateway: ", style={"color": COLORS["text_secondary"]}),
                                html.Span(
                                    id="gateway-name-display",
                                    children=gateway_id[:8] + "...",
                                    style={"color": COLORS["primary"]},
                                ),
                            ]
                        ),
                        html.P(
                            [
                                html.Span("ID: ", className="text-muted"),
                                html.Code(gateway_id, style={"color": COLORS["info"]}),
                                html.Span(" | ", className="text-muted mx-2"),
                                html.Span("Site: ", className="text-muted"),
                                html.Span(
                                    id="gateway-site-display",
                                    children="Loading...",
                                    style={"color": COLORS["text_primary"]},
                                ),
                            ]
                        ),
                    ],
                    width=8,
                ),
                dbc.Col(
                    [
                        html.Div(
                            [
                                html.Span(
                                    id="gateway-status-badge",
                                    children="Loading...",
                                    className="badge bg-secondary",
                                ),
                                html.Br(),
                                html.Small(
                                    id="gateway-last-seen", children="", className="text-muted"
                                ),
                            ],
                            className="text-end",
                        )
                    ],
                    width=4,
                ),
            ],
            className="mb-4 mt-3",
        )

    def _build_status_row(self) -> dbc.Row:
        """Build gateway status cards row."""
        return dbc.Row(
            [
                dbc.Col(StatusCards.build_card("gw-ports-up", "Ports Up", "0", "healthy"), width=2),
                dbc.Col(
                    StatusCards.build_card("gw-ports-down", "Ports Down", "0", "critical"), width=2
                ),
                dbc.Col(StatusCards.build_card("gw-vpn-peers", "VPN Peers", "0", "info"), width=2),
                dbc.Col(StatusCards.build_card("gw-cpu-pct", "CPU %", "-", "normal"), width=2),
                dbc.Col(
                    StatusCards.build_card("gw-memory-pct", "Memory %", "-", "normal"), width=2
                ),
                dbc.Col(StatusCards.build_card("gw-uptime", "Uptime", "-", "info"), width=2),
            ],
            className="mb-4",
        )

    def _build_wan_ports_card(self) -> dbc.Card:
        """Build the WAN ports table card."""
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Span("WAN Ports"),
                        html.Small(" - click port name for details", className="text-muted ms-2"),
                    ]
                ),
                dbc.CardBody(
                    [
                        dash_table.DataTable(
                            id="gw-wan-ports-table",
                            columns=[
                                {"name": "Port", "id": "port_name", "presentation": "markdown"},
                                {"name": "Status", "id": "status"},
                                {"name": "Speed", "id": "speed_mbps"},
                                {"name": "RX (Mbps)", "id": "rx_mbps"},
                                {"name": "TX (Mbps)", "id": "tx_mbps"},
                                {"name": "Util %", "id": "utilization"},
                            ],
                            style_cell={
                                "backgroundColor": COLORS["bg_secondary"],
                                "color": COLORS["text_primary"],
                                "textAlign": "left",
                                "border": f"1px solid {COLORS['bg_border']}",
                                "padding": "8px",
                            },
                            style_header={
                                "backgroundColor": COLORS["bg_card"],
                                "fontWeight": "bold",
                                "borderBottom": f"2px solid {COLORS['primary']}",
                            },
                            style_data_conditional=[
                                {
                                    "if": {"filter_query": "{status} = down"},
                                    "backgroundColor": "#dc3545",
                                    "color": "white",
                                },
                                {
                                    "if": {"filter_query": "{utilization} > 80"},
                                    "backgroundColor": "#fd7e14",
                                    "color": "white",
                                },
                            ],
                            page_size=10,
                            markdown_options={"link_target": "_self"},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_vpn_peers_card(self) -> dbc.Card:
        """Build the VPN peers table card."""
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Span("VPN Peer Paths"),
                        html.Small(" - click peer name for details", className="text-muted ms-2"),
                    ]
                ),
                dbc.CardBody(
                    [
                        dash_table.DataTable(
                            id="gw-vpn-peers-table",
                            columns=[
                                {"name": "Peer", "id": "peer_name", "presentation": "markdown"},
                                {"name": "Status", "id": "path_status"},
                                {"name": "Loss %", "id": "loss_pct"},
                                {"name": "Latency", "id": "latency_ms"},
                                {"name": "Jitter", "id": "jitter_ms"},
                                {"name": "MOS", "id": "mos_score"},
                            ],
                            style_cell={
                                "backgroundColor": COLORS["bg_secondary"],
                                "color": COLORS["text_primary"],
                                "textAlign": "left",
                                "border": f"1px solid {COLORS['bg_border']}",
                                "padding": "8px",
                            },
                            style_header={
                                "backgroundColor": COLORS["bg_card"],
                                "fontWeight": "bold",
                                "borderBottom": f"2px solid {COLORS['warning']}",
                            },
                            style_data_conditional=[
                                {
                                    "if": {"filter_query": "{path_status} = down"},
                                    "backgroundColor": "#dc3545",
                                    "color": "white",
                                },
                                {
                                    "if": {"filter_query": "{loss_pct} > 1"},
                                    "backgroundColor": "#fd7e14",
                                    "color": "white",
                                },
                            ],
                            page_size=10,
                            markdown_options={"link_target": "_self"},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_bandwidth_chart_card(self) -> dbc.Card:
        """Build the aggregate bandwidth chart card."""
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Span("Gateway Bandwidth (24h)"),
                        html.Small(" - all WAN ports combined", className="text-muted ms-2"),
                    ]
                ),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="gw-bandwidth-chart",
                            style={"height": "300px"},
                            config={"responsive": True, "displayModeBar": True},
                        )
                    ]
                ),
            ]
        )

    def _build_device_metrics_card(self) -> dbc.Card:
        """Build the device metrics chart card."""
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Span("Device Metrics (24h)"),
                        html.Small(" - CPU and memory utilization", className="text-muted ms-2"),
                    ]
                ),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="gw-device-metrics-chart",
                            style={"height": "300px"},
                            config={"responsive": True, "displayModeBar": True},
                        )
                    ]
                ),
            ]
        )

    @staticmethod
    def format_wan_port_row(site_id: str, port_data: Dict, gateway_id: str) -> Dict[str, Any]:
        """
        Format a WAN port record for table display with clickable link.

        Args:
            site_id: Site ID for the port
            port_data: Raw port data from API
            gateway_id: Gateway device ID

        Returns:
            Formatted row dictionary with markdown link
        """
        port_id = port_data.get("port_id", port_data.get("name", "unknown"))
        port_name = port_data.get("name", port_id)

        # Create markdown link for port name
        port_link = f"[{port_name}](/port/{site_id}/{port_id}?gateway_id={gateway_id})"

        return {
            "port_name": port_link,
            "status": port_data.get("status", "unknown"),
            "speed_mbps": port_data.get("speed_mbps", "-"),
            "rx_mbps": f"{port_data.get('rx_bps', 0) / 1_000_000:.1f}",
            "tx_mbps": f"{port_data.get('tx_bps', 0) / 1_000_000:.1f}",
            "utilization": f"{port_data.get('utilization_pct', 0):.1f}",
        }

    @staticmethod
    def format_vpn_peer_row(site_id: str, peer_data: Dict) -> Dict[str, Any]:
        """
        Format a VPN peer record for table display with clickable link.

        Args:
            site_id: Site ID for the peer
            peer_data: Raw peer data from API

        Returns:
            Formatted row dictionary with markdown link
        """
        peer_id = peer_data.get("peer_id", peer_data.get("mac", "unknown"))
        peer_name = peer_data.get("peer_name", peer_data.get("peer_site_name", peer_id))

        # Create markdown link for peer name
        peer_link = f"[{peer_name}](/vpn/{site_id}/{peer_id})"

        return {
            "peer_name": peer_link,
            "path_status": peer_data.get("path_status", "unknown"),
            "loss_pct": f"{peer_data.get('loss', 0):.2f}",
            "latency_ms": f"{peer_data.get('latency', 0):.1f}",
            "jitter_ms": f"{peer_data.get('jitter', 0):.1f}",
            "mos_score": f"{peer_data.get('mos', 0):.2f}",
        }
