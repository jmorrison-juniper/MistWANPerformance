"""
MistWANPerformance Dashboard - Port Detail Page

Dedicated page for viewing WAN port statistics including:
- Port status and configuration
- Bandwidth utilization time-series (rx_bps/tx_bps)
- Error counters and packet statistics
- Utilization gauge
- Historical trends
"""

import logging
from typing import Any

import dash_bootstrap_components as dbc
from dash import dcc, html

from src.dashboard.pages.shared import (
    COLORS,
    REFRESH_INTERVAL_MS,
    NavigationBar,
    StatusCards,
)

logger = logging.getLogger(__name__)


class PortPage:
    """
    Port detail page showing interface-specific statistics.

    URL Pattern: /port/<site_id>/<port_id>?gateway_id=<gateway_id>

    Displays:
    - Port identification and status
    - Current bandwidth utilization
    - Bandwidth time-series chart
    - Utilization gauge
    - Packet counters and errors
    - Configuration details
    """

    PAGE_ID = "port-page"

    def __init__(self, data_provider: Any | None = None):
        """
        Initialize port page.

        Args:
            data_provider: Data provider instance for live data
        """
        self.data_provider = data_provider

    def build_layout(
        self,
        site_id: str,
        port_id: str,
        gateway_id: str | None = None,
        data_provider: Any | None = None,
    ) -> html.Div:
        """
        Build the port detail page layout.

        Args:
            site_id: Site ID from URL
            port_id: Port/interface ID from URL
            gateway_id: Optional gateway ID from query string
            data_provider: Optional data provider (overrides instance provider)

        Returns:
            Complete page layout
        """
        # Use provided data_provider or fall back to instance provider
        if data_provider is not None:
            self.data_provider = data_provider

        # Build breadcrumbs
        breadcrumbs = []
        if gateway_id:
            breadcrumbs.append(
                {"label": "Gateway", "href": f"/gateway/{gateway_id}?site_id={site_id}"}
            )
        breadcrumbs.append({"label": "Port Details", "href": None})

        return html.Div(
            [
                # Store port context
                dcc.Store(
                    id="port-context",
                    data={"site_id": site_id, "port_id": port_id, "gateway_id": gateway_id},
                ),
                # Navigation bar
                NavigationBar.build("Port Details", breadcrumbs),
                # Main container
                dbc.Container(
                    [
                        # Header with port info
                        self._build_header(site_id, port_id),
                        # Status cards row
                        self._build_status_row(),
                        # Main content - gauges and current stats
                        dbc.Row(
                            [
                                # Utilization gauge
                                dbc.Col([self._build_utilization_gauge_card()], width=4),
                                # Current stats
                                dbc.Col([self._build_current_stats_card()], width=4),
                                # Configuration
                                dbc.Col([self._build_config_card()], width=4),
                            ],
                            className="mb-4",
                        ),
                        # Bandwidth time-series
                        dbc.Row(
                            [dbc.Col([self._build_bandwidth_chart_card()], width=12)],
                            className="mb-4",
                        ),
                        # Packet statistics
                        dbc.Row(
                            [
                                dbc.Col([self._build_packet_stats_card()], width=6),
                                dbc.Col([self._build_error_stats_card()], width=6),
                            ]
                        ),
                        # Refresh interval
                        dcc.Interval(
                            id="port-refresh-interval", interval=REFRESH_INTERVAL_MS, n_intervals=0
                        ),
                    ],
                    fluid=True,
                ),
            ],
            id=self.PAGE_ID,
        )

    def _build_header(self, site_id: str, port_id: str) -> dbc.Row:
        """Build the page header with port identification."""
        return dbc.Row(
            [
                dbc.Col(
                    [
                        html.H2(
                            [
                                html.Span("Port: ", style={"color": COLORS["text_secondary"]}),
                                html.Span(
                                    id="port-name-display",
                                    children=port_id,
                                    style={"color": COLORS["info"]},
                                ),
                            ]
                        ),
                        html.P(
                            [
                                html.Span("Site: ", className="text-muted"),
                                html.Span(
                                    id="port-site-display",
                                    children=site_id[:8] + "...",
                                    style={"color": COLORS["text_primary"]},
                                ),
                                html.Span(" | ", className="text-muted mx-2"),
                                html.Span("Gateway: ", className="text-muted"),
                                html.Span(
                                    id="port-gateway-link",
                                    children="Loading...",
                                    style={"color": COLORS["primary"]},
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
                                    id="port-status-badge",
                                    children="Loading...",
                                    className="badge bg-secondary",
                                ),
                                html.Br(),
                                html.Small(
                                    id="port-last-updated", children="", className="text-muted"
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
        """Build port status cards row."""
        return dbc.Row(
            [
                dbc.Col(StatusCards.build_card("port-speed", "Speed (Mbps)", "-", "info"), width=2),
                dbc.Col(
                    StatusCards.build_card("port-rx-mbps", "RX (Mbps)", "0.0", "info"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("port-tx-mbps", "TX (Mbps)", "0.0", "primary"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("port-util-pct", "Utilization %", "0.0", "normal"),
                    width=2,
                ),
                dbc.Col(
                    StatusCards.build_card("port-rx-errors", "RX Errors", "0", "normal"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("port-tx-errors", "TX Errors", "0", "normal"), width=2
                ),
            ],
            className="mb-4",
        )

    def _build_utilization_gauge_card(self) -> dbc.Card:
        """Build the utilization gauge card."""
        return dbc.Card(
            [
                dbc.CardHeader("Current Utilization"),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="port-utilization-gauge",
                            style={"height": "200px"},
                            config={"responsive": True, "displayModeBar": False},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_current_stats_card(self) -> dbc.Card:
        """Build current statistics card."""
        return dbc.Card(
            [
                dbc.CardHeader("Current Statistics"),
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("RX Bytes:", className="text-muted"),
                                                html.Td(id="port-rx-bytes", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("TX Bytes:", className="text-muted"),
                                                html.Td(id="port-tx-bytes", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("RX Packets:", className="text-muted"),
                                                html.Td(id="port-rx-packets", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("TX Packets:", className="text-muted"),
                                                html.Td(id="port-tx-packets", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("MTU:", className="text-muted"),
                                                html.Td(id="port-mtu", children="-"),
                                            ]
                                        ),
                                    ]
                                )
                            ],
                            className="table table-sm table-dark",
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_config_card(self) -> dbc.Card:
        """Build port configuration card."""
        return dbc.Card(
            [
                dbc.CardHeader("Configuration"),
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("Type:", className="text-muted"),
                                                html.Td(id="port-type", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Role:", className="text-muted"),
                                                html.Td(id="port-role", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Provider:", className="text-muted"),
                                                html.Td(id="port-provider", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("IP Address:", className="text-muted"),
                                                html.Td(id="port-ip", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("MAC:", className="text-muted"),
                                                html.Td(id="port-mac", children="-"),
                                            ]
                                        ),
                                    ]
                                )
                            ],
                            className="table table-sm table-dark",
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_bandwidth_chart_card(self) -> dbc.Card:
        """Build the bandwidth time-series chart card."""
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Span("Bandwidth Time-Series"),
                        html.Span(" | ", className="text-muted mx-2"),
                        dcc.Dropdown(
                            id="port-time-range-selector",
                            options=[
                                {"label": "Last 6 Hours", "value": 6},
                                {"label": "Last 12 Hours", "value": 12},
                                {"label": "Last 24 Hours", "value": 24},
                                {"label": "Last 7 Days", "value": 168},
                            ],
                            value=24,
                            clearable=False,
                            style={
                                "width": "150px",
                                "display": "inline-block",
                                "backgroundColor": COLORS["bg_secondary"],
                            },
                        ),
                    ]
                ),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="port-bandwidth-chart",
                            style={"height": "350px"},
                            config={"responsive": True, "displayModeBar": True},
                        )
                    ]
                ),
            ]
        )

    def _build_packet_stats_card(self) -> dbc.Card:
        """Build packet statistics card."""
        return dbc.Card(
            [
                dbc.CardHeader("Packet Statistics"),
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Thead(
                                    [html.Tr([html.Th("Metric"), html.Th("RX"), html.Th("TX")])]
                                ),
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("Unicast"),
                                                html.Td(id="port-rx-unicast", children="-"),
                                                html.Td(id="port-tx-unicast", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Multicast"),
                                                html.Td(id="port-rx-multicast", children="-"),
                                                html.Td(id="port-tx-multicast", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Broadcast"),
                                                html.Td(id="port-rx-broadcast", children="-"),
                                                html.Td(id="port-tx-broadcast", children="-"),
                                            ]
                                        ),
                                    ]
                                ),
                            ],
                            className="table table-sm table-dark",
                        )
                    ]
                ),
            ]
        )

    def _build_error_stats_card(self) -> dbc.Card:
        """Build error statistics card."""
        return dbc.Card(
            [
                dbc.CardHeader("Error Counters"),
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Thead(
                                    [html.Tr([html.Th("Error Type"), html.Th("RX"), html.Th("TX")])]
                                ),
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("Errors"),
                                                html.Td(id="port-rx-err-count", children="0"),
                                                html.Td(id="port-tx-err-count", children="0"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Drops"),
                                                html.Td(id="port-rx-drops", children="0"),
                                                html.Td(id="port-tx-drops", children="0"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("CRC Errors"),
                                                html.Td(id="port-rx-crc", children="0"),
                                                html.Td(id="port-tx-crc", children="0"),
                                            ]
                                        ),
                                    ]
                                ),
                            ],
                            className="table table-sm table-dark",
                        )
                    ]
                ),
            ]
        )

    @staticmethod
    def format_bytes(byte_count: int) -> str:
        """
        Format byte count for human-readable display.

        Args:
            byte_count: Raw byte count

        Returns:
            Formatted string (e.g., "1.23 GB")
        """
        if byte_count >= 1_000_000_000_000:
            return f"{byte_count / 1_000_000_000_000:.2f} TB"
        elif byte_count >= 1_000_000_000:
            return f"{byte_count / 1_000_000_000:.2f} GB"
        elif byte_count >= 1_000_000:
            return f"{byte_count / 1_000_000:.2f} MB"
        elif byte_count >= 1_000:
            return f"{byte_count / 1_000:.2f} KB"
        return f"{byte_count} B"
