"""
MistWANPerformance Dashboard - VPN Peer Detail Page

Dedicated page for viewing VPN peer path statistics including:
- Peer identification and status
- Quality metrics (loss, latency, jitter, MOS)
- Quality time-series charts
- Path statistics
- Historical trends
"""

import logging
from typing import Any

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html

from src.dashboard.pages.shared import (
    COLORS,
    REFRESH_INTERVAL_MS,
    NavigationBar,
    StatusCards,
)

logger = logging.getLogger(__name__)


class VPNPeerPage:
    """
    VPN peer detail page showing peer path quality metrics.

    URL Pattern: /vpn/<site_id>/<peer_id>

    Displays:
    - Peer identification and status
    - Quality metrics (loss, latency, jitter, MOS)
    - Quality gauges
    - Quality time-series chart
    - Path statistics
    - Historical comparison
    """

    PAGE_ID = "vpn-peer-page"

    def __init__(self, data_provider: Any | None = None):
        """
        Initialize VPN peer page.

        Args:
            data_provider: Data provider instance for live data
        """
        self.data_provider = data_provider

    def build_layout(
        self, site_id: str, peer_id: str, data_provider: Any | None = None
    ) -> html.Div:
        """
        Build the VPN peer detail page layout.

        Args:
            site_id: Site ID from URL
            peer_id: VPN peer ID from URL
            data_provider: Optional data provider (overrides instance provider)

        Returns:
            Complete page layout
        """
        # Use provided data_provider or fall back to instance provider
        if data_provider is not None:
            self.data_provider = data_provider
        breadcrumbs = [{"label": "VPN Peer Details", "href": None}]

        return html.Div(
            [
                # Store peer context
                dcc.Store(id="vpn-peer-context", data={"site_id": site_id, "peer_id": peer_id}),
                # Navigation bar
                NavigationBar.build("VPN Peer Details", breadcrumbs),
                # Main container
                dbc.Container(
                    [
                        # Header with peer info
                        self._build_header(site_id, peer_id),
                        # Status cards row
                        self._build_status_row(),
                        # Quality gauges row
                        dbc.Row(
                            [
                                dbc.Col([self._build_loss_gauge_card()], width=3),
                                dbc.Col([self._build_latency_gauge_card()], width=3),
                                dbc.Col([self._build_jitter_gauge_card()], width=3),
                                dbc.Col([self._build_mos_gauge_card()], width=3),
                            ],
                            className="mb-4",
                        ),
                        # Quality time-series
                        dbc.Row(
                            [dbc.Col([self._build_quality_chart_card()], width=12)],
                            className="mb-4",
                        ),
                        # Path details and statistics
                        dbc.Row(
                            [
                                dbc.Col([self._build_path_details_card()], width=6),
                                dbc.Col([self._build_path_stats_card()], width=6),
                            ]
                        ),
                        # Refresh interval
                        dcc.Interval(
                            id="vpn-peer-refresh-interval",
                            interval=REFRESH_INTERVAL_MS,
                            n_intervals=0,
                        ),
                    ],
                    fluid=True,
                ),
            ],
            id=self.PAGE_ID,
        )

    def _build_header(self, site_id: str, peer_id: str) -> dbc.Row:
        """Build the page header with peer identification."""
        return dbc.Row(
            [
                dbc.Col(
                    [
                        html.H2(
                            [
                                html.Span("VPN Peer: ", style={"color": COLORS["text_secondary"]}),
                                html.Span(
                                    id="vpn-peer-name-display",
                                    children=peer_id[:12] + "..." if len(peer_id) > 15 else peer_id,
                                    style={"color": COLORS["warning"]},
                                ),
                            ]
                        ),
                        html.P(
                            [
                                html.Span("Local Site: ", className="text-muted"),
                                html.Span(
                                    id="vpn-local-site-display",
                                    children=site_id[:8] + "...",
                                    style={"color": COLORS["text_primary"]},
                                ),
                                html.Span(" <-> ", className="text-muted mx-2"),
                                html.Span("Remote Site: ", className="text-muted"),
                                html.Span(
                                    id="vpn-remote-site-display",
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
                                    id="vpn-peer-status-badge",
                                    children="Loading...",
                                    className="badge bg-secondary",
                                ),
                                html.Br(),
                                html.Small(
                                    id="vpn-peer-last-updated", children="", className="text-muted"
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
        """Build VPN peer status cards row."""
        return dbc.Row(
            [
                dbc.Col(
                    StatusCards.build_card("vpn-path-status", "Path Status", "-", "normal"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("vpn-loss-pct", "Loss %", "0.00", "healthy"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("vpn-latency-ms", "Latency (ms)", "0", "info"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("vpn-jitter-ms", "Jitter (ms)", "0", "info"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("vpn-mos-score", "MOS Score", "-", "healthy"), width=2
                ),
                dbc.Col(StatusCards.build_card("vpn-path-mtu", "Path MTU", "-", "normal"), width=2),
            ],
            className="mb-4",
        )

    def _build_loss_gauge_card(self) -> dbc.Card:
        """Build the packet loss gauge card."""
        return dbc.Card(
            [
                dbc.CardHeader("Packet Loss"),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="vpn-loss-gauge",
                            style={"height": "180px"},
                            config={"responsive": True, "displayModeBar": False},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_latency_gauge_card(self) -> dbc.Card:
        """Build the latency gauge card."""
        return dbc.Card(
            [
                dbc.CardHeader("Latency"),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="vpn-latency-gauge",
                            style={"height": "180px"},
                            config={"responsive": True, "displayModeBar": False},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_jitter_gauge_card(self) -> dbc.Card:
        """Build the jitter gauge card."""
        return dbc.Card(
            [
                dbc.CardHeader("Jitter"),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="vpn-jitter-gauge",
                            style={"height": "180px"},
                            config={"responsive": True, "displayModeBar": False},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_mos_gauge_card(self) -> dbc.Card:
        """Build the MOS score gauge card."""
        return dbc.Card(
            [
                dbc.CardHeader("MOS Score"),
                dbc.CardBody(
                    [
                        dcc.Graph(
                            id="vpn-mos-gauge",
                            style={"height": "180px"},
                            config={"responsive": True, "displayModeBar": False},
                        )
                    ]
                ),
            ],
            className="h-100",
        )

    def _build_quality_chart_card(self) -> dbc.Card:
        """Build the quality time-series chart card."""
        return dbc.Card(
            [
                dbc.CardHeader(
                    [
                        html.Span("Quality Metrics Time-Series"),
                        html.Span(" | ", className="text-muted mx-2"),
                        dcc.Dropdown(
                            id="vpn-time-range-selector",
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
                            id="vpn-peer-quality-chart",
                            style={"height": "350px"},
                            config={"responsive": True, "displayModeBar": True},
                        )
                    ]
                ),
            ]
        )

    def _build_path_details_card(self) -> dbc.Card:
        """Build path details card."""
        return dbc.Card(
            [
                dbc.CardHeader("Path Details"),
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("Peer MAC:", className="text-muted"),
                                                html.Td(id="vpn-peer-mac", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Peer IP:", className="text-muted"),
                                                html.Td(id="vpn-peer-ip", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Local IP:", className="text-muted"),
                                                html.Td(id="vpn-local-ip", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Path Type:", className="text-muted"),
                                                html.Td(id="vpn-path-type", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("Tunnel:", className="text-muted"),
                                                html.Td(id="vpn-tunnel-name", children="-"),
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

    def _build_path_stats_card(self) -> dbc.Card:
        """Build path statistics card."""
        return dbc.Card(
            [
                dbc.CardHeader("Path Statistics"),
                dbc.CardBody(
                    [
                        html.Table(
                            [
                                html.Tbody(
                                    [
                                        html.Tr(
                                            [
                                                html.Td("Uptime:", className="text-muted"),
                                                html.Td(id="vpn-path-uptime", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("TX Bytes:", className="text-muted"),
                                                html.Td(id="vpn-tx-bytes", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("RX Bytes:", className="text-muted"),
                                                html.Td(id="vpn-rx-bytes", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("TX Packets:", className="text-muted"),
                                                html.Td(id="vpn-tx-packets", children="-"),
                                            ]
                                        ),
                                        html.Tr(
                                            [
                                                html.Td("RX Packets:", className="text-muted"),
                                                html.Td(id="vpn-rx-packets", children="-"),
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

    @staticmethod
    def build_loss_gauge(loss_pct: float) -> go.Figure:
        """
        Build a gauge for packet loss percentage.

        Args:
            loss_pct: Current loss percentage (0-100)

        Returns:
            Plotly gauge figure
        """
        # Determine color based on thresholds
        if loss_pct >= 5:
            bar_color = COLORS["critical"]
        elif loss_pct >= 1:
            bar_color = COLORS["high"]
        elif loss_pct >= 0.5:
            bar_color = COLORS["warning"]
        else:
            bar_color = COLORS["healthy"]

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=loss_pct,
                domain={"x": [0, 1], "y": [0, 1]},
                number={"suffix": "%", "font": {"color": COLORS["text_primary"]}},
                gauge={
                    "axis": {"range": [0, 10], "tickwidth": 1},
                    "bar": {"color": bar_color},
                    "bgcolor": COLORS["bg_secondary"],
                    "steps": [
                        {"range": [0, 0.5], "color": "rgba(40, 167, 69, 0.2)"},
                        {"range": [0.5, 1], "color": "rgba(255, 193, 7, 0.2)"},
                        {"range": [1, 5], "color": "rgba(253, 126, 20, 0.2)"},
                        {"range": [5, 10], "color": "rgba(220, 53, 69, 0.2)"},
                    ],
                },
            )
        )

        fig.update_layout(
            template="plotly_dark", margin={"l": 20, "r": 20, "t": 20, "b": 20}, height=150
        )

        return fig

    @staticmethod
    def build_latency_gauge(latency_ms: float) -> go.Figure:
        """
        Build a gauge for latency in milliseconds.

        Args:
            latency_ms: Current latency in ms

        Returns:
            Plotly gauge figure
        """
        # Determine color based on thresholds
        if latency_ms >= 150:
            bar_color = COLORS["critical"]
        elif latency_ms >= 100:
            bar_color = COLORS["high"]
        elif latency_ms >= 50:
            bar_color = COLORS["warning"]
        else:
            bar_color = COLORS["healthy"]

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=latency_ms,
                domain={"x": [0, 1], "y": [0, 1]},
                number={"suffix": " ms", "font": {"color": COLORS["text_primary"]}},
                gauge={
                    "axis": {"range": [0, 200], "tickwidth": 1},
                    "bar": {"color": bar_color},
                    "bgcolor": COLORS["bg_secondary"],
                    "steps": [
                        {"range": [0, 50], "color": "rgba(40, 167, 69, 0.2)"},
                        {"range": [50, 100], "color": "rgba(255, 193, 7, 0.2)"},
                        {"range": [100, 150], "color": "rgba(253, 126, 20, 0.2)"},
                        {"range": [150, 200], "color": "rgba(220, 53, 69, 0.2)"},
                    ],
                },
            )
        )

        fig.update_layout(
            template="plotly_dark", margin={"l": 20, "r": 20, "t": 20, "b": 20}, height=150
        )

        return fig

    @staticmethod
    def build_jitter_gauge(jitter_ms: float) -> go.Figure:
        """
        Build a gauge for jitter in milliseconds.

        Args:
            jitter_ms: Current jitter in ms

        Returns:
            Plotly gauge figure
        """
        # Determine color based on thresholds
        if jitter_ms >= 50:
            bar_color = COLORS["critical"]
        elif jitter_ms >= 30:
            bar_color = COLORS["high"]
        elif jitter_ms >= 10:
            bar_color = COLORS["warning"]
        else:
            bar_color = COLORS["healthy"]

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=jitter_ms,
                domain={"x": [0, 1], "y": [0, 1]},
                number={"suffix": " ms", "font": {"color": COLORS["text_primary"]}},
                gauge={
                    "axis": {"range": [0, 100], "tickwidth": 1},
                    "bar": {"color": bar_color},
                    "bgcolor": COLORS["bg_secondary"],
                    "steps": [
                        {"range": [0, 10], "color": "rgba(40, 167, 69, 0.2)"},
                        {"range": [10, 30], "color": "rgba(255, 193, 7, 0.2)"},
                        {"range": [30, 50], "color": "rgba(253, 126, 20, 0.2)"},
                        {"range": [50, 100], "color": "rgba(220, 53, 69, 0.2)"},
                    ],
                },
            )
        )

        fig.update_layout(
            template="plotly_dark", margin={"l": 20, "r": 20, "t": 20, "b": 20}, height=150
        )

        return fig

    @staticmethod
    def build_mos_gauge(mos_score: float) -> go.Figure:
        """
        Build a gauge for MOS (Mean Opinion Score).

        Args:
            mos_score: Current MOS score (1-5)

        Returns:
            Plotly gauge figure
        """
        # Determine color based on MOS thresholds
        # MOS: 5=Excellent, 4=Good, 3=Fair, 2=Poor, 1=Bad
        if mos_score >= 4:
            bar_color = COLORS["healthy"]
        elif mos_score >= 3:
            bar_color = COLORS["warning"]
        elif mos_score >= 2:
            bar_color = COLORS["high"]
        else:
            bar_color = COLORS["critical"]

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=mos_score,
                domain={"x": [0, 1], "y": [0, 1]},
                number={"font": {"color": COLORS["text_primary"]}},
                gauge={
                    "axis": {"range": [1, 5], "tickwidth": 1},
                    "bar": {"color": bar_color},
                    "bgcolor": COLORS["bg_secondary"],
                    "steps": [
                        {"range": [1, 2], "color": "rgba(220, 53, 69, 0.2)"},
                        {"range": [2, 3], "color": "rgba(253, 126, 20, 0.2)"},
                        {"range": [3, 4], "color": "rgba(255, 193, 7, 0.2)"},
                        {"range": [4, 5], "color": "rgba(40, 167, 69, 0.2)"},
                    ],
                },
            )
        )

        fig.update_layout(
            template="plotly_dark", margin={"l": 20, "r": 20, "t": 20, "b": 20}, height=150
        )

        return fig
