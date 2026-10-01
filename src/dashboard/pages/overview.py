"""
MistWANPerformance Dashboard - Overview Page

Main dashboard page with site summaries, alerts, and aggregate metrics.
This is the landing page showing overall WAN health at a glance.
"""

import logging
from typing import Any

import dash_bootstrap_components as dbc
from dash import dash_table, dcc, html

from src.dashboard.pages.shared import (
    COLORS,
    REFRESH_INTERVAL_MS,
    StatusCards,
)

logger = logging.getLogger(__name__)


class OverviewPage:
    """
    Main dashboard overview page.

    Displays:
    - Site status summary cards
    - Gateway health overview
    - Circuit utilization summary
    - SLE metrics
    - VPN peer status
    - Top congested circuits table
    - Active alerts
    - Utilization trends
    """

    PAGE_ID = "overview-page"

    def __init__(self, data_provider: Any | None = None):
        """
        Initialize overview page.

        Args:
            data_provider: Data provider instance for live data
        """
        self.data_provider = data_provider

    def build_layout(self, data_provider: Any | None = None) -> html.Div:
        """
        Build the overview page layout.

        Args:
            data_provider: Optional data provider (overrides instance provider)

        Returns:
            Complete page layout with all overview components
        """
        # Use provided data_provider or fall back to instance provider
        if data_provider is not None:
            self.data_provider = data_provider
        return html.Div(
            [
                # Hidden stores for state management
                dcc.Store(id="overview-state", data={}),
                # Backend Status Bar
                self._build_status_bar(),
                # Header
                self._build_header(),
                # Site Overview Cards Row
                self._build_site_cards_row(),
                # Gateway Health Row
                self._build_gateway_cards_row(),
                # Additional Metrics Row
                self._build_metrics_row(),
                # SLE Row
                self._build_sle_row(),
                # VPN Peer Row
                self._build_vpn_row(),
                # Main Content - Tables and Charts
                self._build_main_content(),
                # Trends Row
                self._build_trends_row(),
                # Refresh interval
                dcc.Interval(
                    id="overview-refresh-interval", interval=REFRESH_INTERVAL_MS, n_intervals=0
                ),
                dcc.Interval(id="overview-status-interval", interval=10000, n_intervals=0),
            ],
            id=self.PAGE_ID,
            className="container-fluid",
        )

    def _build_status_bar(self) -> dbc.Row:
        """Build the backend status bar."""
        return dbc.Row(
            [
                dbc.Col(
                    [
                        html.Div(
                            [
                                html.Span(
                                    id="backend-status-indicator",
                                    children=[
                                        html.Span(
                                            "[*]",
                                            style={
                                                "color": COLORS["healthy"],
                                                "fontFamily": "monospace",
                                                "marginRight": "8px",
                                                "fontSize": "1.1rem",
                                            },
                                        ),
                                        html.Span(
                                            "Backend Connected",
                                            style={
                                                "color": COLORS["text_primary"],
                                                "fontWeight": "500",
                                            },
                                        ),
                                    ],
                                ),
                                html.Span(
                                    " | ",
                                    style={
                                        "color": COLORS["primary"],
                                        "margin": "0 12px",
                                        "fontWeight": "bold",
                                    },
                                ),
                                html.Span(
                                    id="rate-limit-status-display",
                                    children="API: OK",
                                    style={
                                        "color": COLORS["healthy"],
                                        "fontSize": "0.9rem",
                                        "fontWeight": "500",
                                    },
                                ),
                                html.Span(
                                    " | ",
                                    style={
                                        "color": COLORS["primary"],
                                        "margin": "0 12px",
                                        "fontWeight": "bold",
                                    },
                                ),
                                html.Span(
                                    id="cache-status-display",
                                    children="Cache: Loading...",
                                    style={"color": COLORS["text_primary"], "fontSize": "0.9rem"},
                                ),
                                html.Span(
                                    " | ",
                                    style={
                                        "color": COLORS["primary"],
                                        "margin": "0 12px",
                                        "fontWeight": "bold",
                                    },
                                ),
                                html.Span(
                                    id="refresh-activity-display",
                                    children="Refresh: Idle",
                                    style={"color": COLORS["text_primary"], "fontSize": "0.9rem"},
                                ),
                            ],
                            style={
                                "backgroundColor": "#1e1e1e",
                                "padding": "12px 20px",
                                "borderRadius": "6px",
                                "border": f"2px solid {COLORS['primary']}",
                                "fontSize": "0.95rem",
                                "boxShadow": "0 2px 8px rgba(226, 0, 116, 0.2)",
                            },
                        )
                    ],
                    width=12,
                )
            ],
            className="mb-3 mt-2",
        )

    def _build_header(self) -> dbc.Row:
        """Build the page header."""
        return dbc.Row(
            [
                dbc.Col(
                    [
                        html.H1(
                            "WAN Performance Dashboard",
                            style={"color": COLORS["primary"], "fontWeight": "bold"},
                        ),
                        html.P(
                            "Real-time WAN circuit monitoring for NOC operations",
                            style={"color": COLORS["text_secondary"]},
                        ),
                    ],
                    width=7,
                ),
                dbc.Col([html.Div(id="last-updated", className="text-end text-muted")], width=5),
            ],
            className="mb-4 mt-3",
        )

    def _build_site_cards_row(self) -> dbc.Row:
        """Build the site status cards row."""
        return dbc.Row(
            [
                dbc.Col(StatusCards.build_card("total-sites", "Total Sites", "0"), width=2),
                dbc.Col(
                    StatusCards.build_card("healthy-sites", "Healthy", "0", "healthy"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("degraded-sites", "High Util", "0", "degraded"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("critical-sites", "Critical", "0", "critical"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("active-failovers", "Failovers", "0", "warning"), width=2
                ),
                dbc.Col(StatusCards.build_card("active-alerts", "Alerts", "0", "high"), width=2),
            ],
            className="mb-3",
        )

    def _build_gateway_cards_row(self) -> dbc.Row:
        """Build the gateway health cards row."""
        return dbc.Row(
            [
                dbc.Col(
                    StatusCards.build_card("gateways-online", "Gateways Online", "0", "healthy"),
                    width=2,
                ),
                dbc.Col(
                    StatusCards.build_card("gateways-offline", "Gateways Offline", "0", "critical"),
                    width=2,
                ),
                dbc.Col(
                    StatusCards.build_card("total-circuits", "Circuits Up", "0", "healthy"), width=2
                ),
                dbc.Col(StatusCards.build_card("circuits-down", "Down", "0", "critical"), width=1),
                dbc.Col(
                    StatusCards.build_card("circuits-disabled", "Disabled", "0", "normal"), width=1
                ),
                dbc.Col(
                    StatusCards.build_card("circuits-above-80", "Above 80%", "0", "high"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("avg-utilization", "Avg Util %", "0.0", "info"), width=2
                ),
            ],
            className="mb-3",
        )

    def _build_metrics_row(self) -> dbc.Row:
        """Build additional metrics cards row."""
        return dbc.Row(
            [
                dbc.Col(
                    StatusCards.build_card("max-utilization", "Max Util %", "0.0", "warning"),
                    width=2,
                ),
                dbc.Col(
                    StatusCards.build_card("total-bandwidth", "Total BW (Gbps)", "0.0", "info"),
                    width=2,
                ),
            ],
            className="mb-3",
        )

    def _build_sle_row(self) -> dbc.Row:
        """Build SLE metrics cards row."""
        return dbc.Row(
            [
                dbc.Col(
                    StatusCards.build_card("sle-gateway-health", "SLE Gateway", "-", "info"),
                    width=2,
                ),
                dbc.Col(
                    StatusCards.build_card("sle-wan-link", "SLE WAN Link", "-", "info"), width=2
                ),
                dbc.Col(StatusCards.build_card("sle-app-health", "SLE App", "-", "info"), width=2),
                dbc.Col(
                    StatusCards.build_card("sle-degraded-sites", "SLE Degraded", "0", "warning"),
                    width=2,
                ),
                dbc.Col(StatusCards.build_card("alarms-total", "Alarms", "0", "high"), width=2),
                dbc.Col(
                    StatusCards.build_card("alarms-critical", "Critical", "0", "critical"), width=2
                ),
            ],
            className="mb-3",
        )

    def _build_vpn_row(self) -> dbc.Row:
        """Build VPN peer path cards row."""
        return dbc.Row(
            [
                dbc.Col(
                    StatusCards.build_card("vpn-total-peers", "VPN Peers", "0", "info"), width=2
                ),
                dbc.Col(StatusCards.build_card("vpn-paths-up", "Paths Up", "0", "normal"), width=2),
                dbc.Col(
                    StatusCards.build_card("vpn-paths-down", "Paths Down", "0", "critical"), width=2
                ),
                dbc.Col(
                    StatusCards.build_card("vpn-health-pct", "VPN Health %", "-", "info"), width=2
                ),
            ],
            className="mb-4",
        )

    def _build_main_content(self) -> dbc.Row:
        """Build the main content area with tables and charts."""
        return dbc.Row(
            [
                # Left Column - Tables
                dbc.Col(
                    [
                        # Top Congested Circuits
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [
                                        html.Span("Top 10 Congested Circuits"),
                                        dbc.Button(
                                            "Export CSV",
                                            id="export-congested-btn",
                                            color="secondary",
                                            size="sm",
                                            className="float-end",
                                        ),
                                        dcc.Download(id="download-congested-csv"),
                                    ]
                                ),
                                dbc.CardBody(
                                    [
                                        dash_table.DataTable(
                                            id="top-congested-table",
                                            columns=[
                                                {"name": "Rank", "id": "rank"},
                                                {
                                                    "name": "Site",
                                                    "id": "site_name",
                                                    "presentation": "markdown",
                                                },
                                                {
                                                    "name": "Gateway",
                                                    "id": "gateway_name",
                                                    "presentation": "markdown",
                                                },
                                                {
                                                    "name": "Port",
                                                    "id": "port_id",
                                                    "presentation": "markdown",
                                                },
                                                {"name": "Speed (Mbps)", "id": "bandwidth_mbps"},
                                                {"name": "Utilization %", "id": "metric_value"},
                                                {"name": "Status", "id": "threshold_status"},
                                            ],
                                            style_cell={
                                                "backgroundColor": COLORS["bg_secondary"],
                                                "color": COLORS["text_primary"],
                                                "textAlign": "left",
                                                "cursor": "pointer",
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
                                                    "if": {
                                                        "filter_query": "{threshold_status} = critical"
                                                    },
                                                    "backgroundColor": "#dc3545",
                                                    "color": "white",
                                                },
                                                {
                                                    "if": {
                                                        "filter_query": "{threshold_status} = high"
                                                    },
                                                    "backgroundColor": "#fd7e14",
                                                    "color": "white",
                                                },
                                                {
                                                    "if": {
                                                        "filter_query": "{threshold_status} = warning"
                                                    },
                                                    "backgroundColor": "#ffc107",
                                                    "color": "black",
                                                },
                                            ],
                                            page_size=10,
                                            markdown_options={"link_target": "_self"},
                                        )
                                    ]
                                ),
                            ],
                            className="mb-4",
                        ),
                        # Active Alerts
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [
                                        html.Span("Active Alerts"),
                                        dbc.Button(
                                            "Export CSV",
                                            id="export-alerts-btn",
                                            color="secondary",
                                            size="sm",
                                            className="float-end",
                                        ),
                                        dcc.Download(id="download-alerts-csv"),
                                    ]
                                ),
                                dbc.CardBody([html.Div(id="alerts-list")]),
                            ],
                            className="mb-4",
                        ),
                        # SLE Degraded Sites
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [
                                        html.Span("SLE Degraded Sites (< 90%)"),
                                        dbc.Button(
                                            "Export CSV",
                                            id="export-sle-degraded-btn",
                                            color="secondary",
                                            size="sm",
                                            className="float-end",
                                        ),
                                        dcc.Download(id="download-sle-degraded-csv"),
                                    ]
                                ),
                                dbc.CardBody(
                                    [
                                        dash_table.DataTable(
                                            id="sle-degraded-table",
                                            columns=[
                                                {
                                                    "name": "Site Name",
                                                    "id": "site_name",
                                                    "presentation": "markdown",
                                                },
                                                {"name": "Gateway %", "id": "gateway_health"},
                                                {"name": "WAN Link %", "id": "wan_link"},
                                                {"name": "App Health %", "id": "app_health"},
                                            ],
                                            cell_selectable=True,
                                            style_cell={
                                                "backgroundColor": COLORS["bg_secondary"],
                                                "color": COLORS["text_primary"],
                                                "textAlign": "left",
                                                "cursor": "pointer",
                                                "border": f"1px solid {COLORS['bg_border']}",
                                                "padding": "8px",
                                            },
                                            style_header={
                                                "backgroundColor": COLORS["bg_card"],
                                                "fontWeight": "bold",
                                                "borderBottom": f"2px solid {COLORS['primary']}",
                                            },
                                            page_size=10,
                                            sort_action="native",
                                            filter_action="native",
                                            markdown_options={"link_target": "_self"},
                                        )
                                    ]
                                ),
                            ]
                        ),
                    ],
                    width=6,
                ),
                # Right Column - Charts
                dbc.Col(
                    [
                        # Region Summary
                        dbc.Card(
                            [
                                dbc.CardHeader("Region Summary (click to drill down)"),
                                dbc.CardBody(
                                    [
                                        dcc.Graph(
                                            id="region-chart",
                                            style={"height": "300px"},
                                            config={"responsive": True, "displayModeBar": True},
                                        )
                                    ]
                                ),
                            ],
                            className="mb-4",
                        ),
                        # Utilization Distribution
                        dbc.Card(
                            [
                                dbc.CardHeader("Utilization Distribution"),
                                dbc.CardBody(
                                    [
                                        dcc.Graph(
                                            id="utilization-chart",
                                            style={"height": "300px"},
                                            config={"responsive": True, "displayModeBar": True},
                                        )
                                    ]
                                ),
                            ]
                        ),
                    ],
                    width=6,
                ),
            ],
            className="mb-4",
        )

    def _build_trends_row(self) -> dbc.Row:
        """Build the trends charts row."""
        return dbc.Row(
            [
                dbc.Col(
                    [
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [
                                        html.Span("Real-Time Utilization Trends (24h)"),
                                        html.Small(
                                            " - instantaneous % of capacity",
                                            className="text-muted ms-2",
                                        ),
                                    ]
                                ),
                                dbc.CardBody(
                                    [
                                        dcc.Graph(
                                            id="trends-chart",
                                            style={"height": "250px"},
                                            config={"responsive": True, "displayModeBar": True},
                                        )
                                    ]
                                ),
                            ]
                        )
                    ],
                    width=6,
                ),
                dbc.Col(
                    [
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    [
                                        html.Span("Aggregate Throughput (24h)"),
                                        html.Small(
                                            " - total Mbps across all circuits",
                                            className="text-muted ms-2",
                                        ),
                                    ]
                                ),
                                dbc.CardBody(
                                    [
                                        dcc.Graph(
                                            id="throughput-chart",
                                            style={"height": "250px"},
                                            config={"responsive": True, "displayModeBar": True},
                                        )
                                    ]
                                ),
                            ]
                        )
                    ],
                    width=6,
                ),
            ]
        )
