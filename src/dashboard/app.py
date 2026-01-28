"""
MistWANPerformance - Dashboard Application

Dash/Plotly dashboard for NOC WAN circuit visibility.
Provides real-time monitoring, trends, alerts, drilldowns, and CSV exports.
"""

import csv
import io
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import dash
from dash import dcc, html, dash_table, callback, Input, Output, State
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc  # type: ignore[import-untyped]
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.views.current_state import CurrentStateViews, CircuitCurrentState, AlertSeverity
from src.views.rankings import RankingViews, RankedCircuit


logger = logging.getLogger(__name__)


class WANPerformanceDashboard:
    """
    NOC Dashboard for WAN circuit performance monitoring.
    
    Features:
    - Overview panel with site status counts
    - Top congested circuits table with CSV export
    - Active alerts panel
    - Utilization trends chart
    - Drilldown navigation: Region -> Site -> Circuit -> Time Series
    - Failover status tracker with primary/secondary comparison
    """
    
    # Refresh interval in milliseconds
    REFRESH_INTERVAL_MS = 60000  # 1 minute
    
    # T-Mobile Magenta color scheme (from MistCircuitStats-Redis)
    COLORS = {
        # Primary brand color
        "primary": "#E20074",         # T-Mobile Magenta
        "primary_hover": "#C00062",   # Darker magenta for hover
        "primary_light": "#FF3399",   # Lighter magenta
        # Status colors
        "healthy": "#28a745",         # Green - connected/up/good
        "degraded": "#ffc107",        # Yellow/amber - warning
        "critical": "#dc3545",        # Red - error/down/critical
        "normal": "#6c757d",          # Gray - neutral/inactive
        "warning": "#ffc107",         # Yellow - warning
        "high": "#fd7e14",            # Orange - high severity
        "info": "#17a2b8",            # Cyan - informational
        # Background colors (dark theme)
        "bg_primary": "#1a1a1a",      # Main background
        "bg_secondary": "#2d2d2d",    # Card/component background
        "bg_card": "#363636",         # Card header background
        "bg_border": "#404040",       # Border color
        # Text colors
        "text_primary": "#e0e0e0",    # Primary text
        "text_secondary": "#a0a0a0",  # Secondary/muted text
    }
    
    def __init__(
        self,
        app_name: str = "WAN Performance Dashboard",
        data_provider: Optional[Any] = None
    ):
        """
        Initialize the dashboard.
        
        Args:
            app_name: Application name for title
            data_provider: Optional data provider for live data
        """
        self.app_name = app_name
        self.data_provider = data_provider
        
        # Initialize Dash app with Bootstrap theme
        self.app = dash.Dash(
            __name__,
            external_stylesheets=[dbc.themes.DARKLY],
            title=app_name,
            suppress_callback_exceptions=True
        )
        
        # Apply custom T-Mobile Magenta CSS
        self.app.index_string = self._get_custom_index_string()
        
        # Build layout
        self.app.layout = self._build_layout()
        
        # Register callbacks
        self._register_callbacks()
        
        logger.info(f"[OK] Dashboard initialized: {app_name}")
    
    def _get_custom_index_string(self) -> str:
        """
        Get custom HTML index template with T-Mobile Magenta styling.
        
        Returns:
            Custom HTML template string
        """
        return '''
<!DOCTYPE html>
<html lang="en" data-bs-theme="dark">
    <head>
        {%metas%}
        <title>{%title%}</title>
        {%favicon%}
        {%css%}
        <style>
            /* T-Mobile Magenta Theme - Dark Background */
            :root {
                --tmobile-magenta: #E20074;
                --tmobile-magenta-hover: #C00062;
                --tmobile-magenta-light: #FF3399;
                --bg-dark: #1a1a1a;
                --bg-card: #2d2d2d;
                --bg-card-header: #363636;
                --border-color: #404040;
                --text-primary: #e0e0e0;
                --text-muted: #a0a0a0;
            }
            
            /* Base body styling */
            body {
                background-color: var(--bg-dark) !important;
                color: var(--text-primary) !important;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            }
            
            /* Container background */
            .container-fluid, .container {
                background-color: var(--bg-dark) !important;
            }
            
            /* Override Bootstrap primary with T-Mobile Magenta */
            .text-primary, h1.text-primary, .h1.text-primary {
                color: var(--tmobile-magenta) !important;
            }
            
            .text-muted {
                color: var(--text-muted) !important;
            }
            
            /* Button styling */
            .btn-primary {
                background-color: var(--tmobile-magenta) !important;
                border-color: var(--tmobile-magenta) !important;
                color: #fff !important;
            }
            
            .btn-primary:hover, .btn-primary:focus {
                background-color: var(--tmobile-magenta-hover) !important;
                border-color: var(--tmobile-magenta-hover) !important;
            }
            
            .btn-secondary {
                background-color: #404040 !important;
                border-color: #505050 !important;
            }
            
            .btn-secondary:hover {
                background-color: #505050 !important;
                border-color: #606060 !important;
            }
            
            /* Card styling */
            .card {
                background-color: var(--bg-card) !important;
                border: 1px solid var(--border-color) !important;
                border-radius: 8px;
            }
            
            .card-header {
                background-color: var(--bg-card-header) !important;
                border-bottom: 2px solid var(--tmobile-magenta) !important;
                font-weight: 600;
                color: var(--text-primary) !important;
            }
            
            .card-body {
                background-color: var(--bg-card) !important;
                color: var(--text-primary) !important;
            }
            
            /* Stats cards - large numbers in magenta */
            .display-4, .display-5, .display-6 {
                color: var(--tmobile-magenta) !important;
                font-weight: bold;
            }
            
            /* Row backgrounds */
            .row {
                background-color: transparent !important;
            }
            
            /* Dash DataTable styling */
            .dash-table-container {
                background-color: var(--bg-card) !important;
            }
            
            .dash-spreadsheet-container {
                background-color: var(--bg-card) !important;
            }
            
            .dash-spreadsheet {
                background-color: var(--bg-card) !important;
            }
            
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner th {
                background-color: var(--bg-card-header) !important;
                color: var(--text-primary) !important;
                border-bottom: 2px solid var(--tmobile-magenta) !important;
                font-weight: 600;
            }
            
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td {
                background-color: var(--bg-card) !important;
                color: var(--text-primary) !important;
                border-color: var(--border-color) !important;
            }
            
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner tr:hover td {
                background-color: var(--bg-card-header) !important;
            }
            
            /* Selected row in table */
            .dash-table-container .dash-spreadsheet-container .dash-spreadsheet-inner td.focused {
                background-color: var(--tmobile-magenta) !important;
                color: #fff !important;
            }
            
            /* Alert/Badge styling */
            .alert-danger, .bg-danger {
                background-color: #dc3545 !important;
            }
            
            .alert-warning, .bg-warning {
                background-color: #ffc107 !important;
                color: #000 !important;
            }
            
            .alert-success, .bg-success {
                background-color: #28a745 !important;
            }
            
            .badge {
                font-size: 0.8rem;
                padding: 0.35em 0.65em;
            }
            
            /* Status indicator colors */
            .status-healthy, .text-success {
                color: #28a745 !important;
            }
            
            .status-degraded, .text-warning {
                color: #ffc107 !important;
            }
            
            .status-critical, .text-danger {
                color: #dc3545 !important;
            }
            
            /* Graph/Chart container */
            .js-plotly-plot {
                background-color: transparent !important;
            }
            
            .js-plotly-plot .plotly .modebar {
                background-color: transparent !important;
            }
            
            .js-plotly-plot .plotly .bg {
                fill: var(--bg-card) !important;
            }
            
            /* Links */
            a {
                color: var(--tmobile-magenta);
            }
            
            a:hover {
                color: var(--tmobile-magenta-light);
            }
            
            /* Breadcrumb */
            .breadcrumb {
                background-color: transparent !important;
            }
            
            .breadcrumb-item a {
                color: var(--tmobile-magenta) !important;
            }
            
            .breadcrumb-item.active {
                color: var(--text-muted) !important;
            }
            
            /* Dropdown menus */
            .dropdown-menu {
                background-color: var(--bg-card) !important;
                border-color: var(--border-color) !important;
            }
            
            .dropdown-item {
                color: var(--text-primary) !important;
            }
            
            .dropdown-item:hover {
                background-color: var(--bg-card-header) !important;
            }
            
            /* Form controls */
            .form-control, .form-select {
                background-color: var(--bg-card) !important;
                border-color: var(--border-color) !important;
                color: var(--text-primary) !important;
            }
            
            .form-control:focus, .form-select:focus {
                border-color: var(--tmobile-magenta) !important;
                box-shadow: 0 0 0 0.2rem rgba(226, 0, 116, 0.25) !important;
            }
            
            /* Scrollbar styling for dark theme */
            ::-webkit-scrollbar {
                width: 8px;
                height: 8px;
            }
            
            ::-webkit-scrollbar-track {
                background: var(--bg-dark);
            }
            
            ::-webkit-scrollbar-thumb {
                background: var(--border-color);
                border-radius: 4px;
            }
            
            ::-webkit-scrollbar-thumb:hover {
                background: var(--tmobile-magenta);
            }
        </style>
    </head>
    <body>
        {%app_entry%}
        <footer>
            {%config%}
            {%scripts%}
            {%renderer%}
        </footer>
    </body>
</html>
'''
    
    def _build_layout(self) -> dbc.Container:
        """
        Build the dashboard layout with drilldown navigation.
        
        Returns:
            Dash Bootstrap Container with all components
        """
        return dbc.Container([
            # Hidden stores for drilldown state
            dcc.Store(id="drilldown-state", data={"level": "overview", "region": None, "site": None, "circuit": None}),
            
            # Header
            dbc.Row([
                dbc.Col([
                    html.H1(
                        self.app_name,
                        style={"color": self.COLORS["primary"], "fontWeight": "bold"}
                    ),
                    html.P(
                        "Real-time WAN circuit monitoring for NOC operations",
                        style={"color": self.COLORS["text_secondary"]}
                    )
                ], width=7),
                dbc.Col([
                    # Breadcrumb navigation for drilldowns
                    html.Div(id="breadcrumb-nav", className="mb-2"),
                    html.Div(id="last-updated", className="text-end text-muted"),
                    dcc.Interval(
                        id="refresh-interval",
                        interval=self.REFRESH_INTERVAL_MS,
                        n_intervals=0
                    )
                ], width=5)
            ], className="mb-4 mt-3"),
            
            # Overview Cards Row
            dbc.Row([
                dbc.Col(self._build_status_card("total-sites", "Total Sites", "0"), width=2),
                dbc.Col(self._build_status_card("healthy-sites", "Healthy", "0", "healthy"), width=2),
                dbc.Col(self._build_status_card("degraded-sites", "Degraded", "0", "degraded"), width=2),
                dbc.Col(self._build_status_card("critical-sites", "Critical", "0", "critical"), width=2),
                dbc.Col(self._build_status_card("active-failovers", "Failovers", "0", "warning"), width=2),
                dbc.Col(self._build_status_card("active-alerts", "Alerts", "0", "high"), width=2),
            ], className="mb-4"),
            
            # Drilldown Content Area
            html.Div(id="drilldown-content"),
            
            # Main Content Row (default view)
            html.Div(id="main-content", children=[
                dbc.Row([
                    # Left Column - Tables with Export
                    dbc.Col([
                        # Top Congested Circuits with Export Button
                        dbc.Card([
                            dbc.CardHeader([
                                html.Span("Top 10 Congested Circuits"),
                                dbc.Button(
                                    "Export CSV",
                                    id="export-congested-btn",
                                    color="secondary",
                                    size="sm",
                                    className="float-end"
                                ),
                                dcc.Download(id="download-congested-csv")
                            ]),
                            dbc.CardBody([
                                dash_table.DataTable(
                                    id="top-congested-table",
                                    columns=[
                                        {"name": "Rank", "id": "rank"},
                                        {"name": "Site", "id": "site_name"},
                                        {"name": "Circuit", "id": "circuit_id"},
                                        {"name": "Region", "id": "region"},
                                        {"name": "Utilization", "id": "metric_value"},
                                        {"name": "Status", "id": "threshold_status"}
                                    ],
                                    style_cell={
                                        "backgroundColor": self.COLORS["bg_secondary"],
                                        "color": self.COLORS["text_primary"],
                                        "textAlign": "left",
                                        "cursor": "pointer",
                                        "border": f"1px solid {self.COLORS['bg_border']}",
                                        "padding": "8px"
                                    },
                                    style_header={
                                        "backgroundColor": self.COLORS["bg_card"],
                                        "fontWeight": "bold",
                                        "borderBottom": f"2px solid {self.COLORS['primary']}"
                                    },
                                    style_data_conditional=[  # type: ignore[arg-type]
                                        {
                                            "if": {"filter_query": "{threshold_status} = critical"},
                                            "backgroundColor": "#dc3545",
                                            "color": "white"
                                        },
                                        {
                                            "if": {"filter_query": "{threshold_status} = high"},
                                            "backgroundColor": "#fd7e14",
                                            "color": "white"
                                        },
                                        {
                                            "if": {"filter_query": "{threshold_status} = warning"},
                                            "backgroundColor": "#ffc107",
                                            "color": "black"
                                        }
                                    ],
                                    page_size=10,
                                    row_selectable="single"
                                )
                            ])
                        ], className="mb-4"),
                        
                        # Active Alerts with Export
                        dbc.Card([
                            dbc.CardHeader([
                                html.Span("Active Alerts"),
                                dbc.Button(
                                    "Export CSV",
                                    id="export-alerts-btn",
                                    color="secondary",
                                    size="sm",
                                    className="float-end"
                                ),
                                dcc.Download(id="download-alerts-csv")
                            ]),
                            dbc.CardBody([
                                html.Div(id="alerts-list")
                            ])
                        ])
                    ], width=6),
                    
                    # Right Column - Charts
                    dbc.Col([
                        # Region Summary (clickable for drilldown)
                        dbc.Card([
                            dbc.CardHeader("Region Summary (click to drill down)"),
                            dbc.CardBody([
                                dcc.Graph(id="region-chart", style={"height": "300px"})
                            ])
                        ], className="mb-4"),
                        
                        # Utilization Distribution
                        dbc.Card([
                            dbc.CardHeader("Utilization Distribution"),
                            dbc.CardBody([
                                dcc.Graph(id="utilization-chart", style={"height": "300px"})
                            ])
                        ])
                    ], width=6)
                ], className="mb-4"),
                
                # Bottom Row - Trends
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader("Utilization Trends (24h)"),
                            dbc.CardBody([
                                dcc.Graph(id="trends-chart", style={"height": "250px"})
                            ])
                        ])
                    ])
                ])
            ])
        ], fluid=True)
    
    def _build_status_card(
        self,
        card_id: str,
        title: str,
        value: str,
        status: Optional[str] = None
    ) -> dbc.Card:
        """Build a status overview card."""
        color = self.COLORS.get(status, "#6c757d") if status else "#6c757d"
        
        return dbc.Card([
            dbc.CardBody([
                html.H4(id=card_id, children=value, style={"color": color}),
                html.P(title, className="text-muted mb-0")
            ])
        ], className="text-center")
    
    def _build_region_drilldown(self, region: str, data: Dict) -> html.Div:
        """Build region drilldown view with site list."""
        sites = data.get("region_sites", {}).get(region, [])
        
        return html.Div([
            dbc.Card([
                dbc.CardHeader([
                    html.H5(f"Region: {region} - Site List"),
                    dbc.Button(
                        "Export CSV",
                        id="export-region-sites-btn",
                        color="secondary",
                        size="sm",
                        className="float-end"
                    ),
                    dcc.Download(id="download-region-sites-csv")
                ]),
                dbc.CardBody([
                    dash_table.DataTable(
                        id="region-sites-table",
                        columns=[
                            {"name": "Site Name", "id": "site_name"},
                            {"name": "Site ID", "id": "site_id"},
                            {"name": "Circuit Count", "id": "circuit_count"},
                            {"name": "Avg Utilization", "id": "avg_utilization"},
                            {"name": "Status", "id": "status"}
                        ],
                        data=sites,
                        style_cell={
                            "backgroundColor": self.COLORS["bg_secondary"],
                            "color": self.COLORS["text_primary"],
                            "textAlign": "left",
                            "cursor": "pointer",
                            "border": f"1px solid {self.COLORS['bg_border']}",
                            "padding": "8px"
                        },
                        style_header={
                            "backgroundColor": self.COLORS["bg_card"],
                            "fontWeight": "bold",
                            "borderBottom": f"2px solid {self.COLORS['primary']}"
                        },
                        page_size=15,
                        row_selectable="single"
                    )
                ])
            ])
        ])
    
    def _build_site_drilldown(self, site_id: str, data: Dict) -> html.Div:
        """Build site drilldown view with circuit list."""
        circuits = data.get("site_circuits", {}).get(site_id, [])
        site_name = data.get("site_names", {}).get(site_id, site_id)
        
        return html.Div([
            dbc.Card([
                dbc.CardHeader([
                    html.H5(f"Site: {site_name} - Circuit List"),
                    dbc.Button(
                        "Export CSV",
                        id="export-site-circuits-btn",
                        color="secondary",
                        size="sm",
                        className="float-end"
                    ),
                    dcc.Download(id="download-site-circuits-csv")
                ]),
                dbc.CardBody([
                    dash_table.DataTable(
                        id="site-circuits-table",
                        columns=[
                            {"name": "Circuit ID", "id": "circuit_id"},
                            {"name": "Role", "id": "role"},
                            {"name": "Status", "id": "status"},
                            {"name": "Utilization %", "id": "utilization_pct"},
                            {"name": "Availability %", "id": "availability_pct"},
                            {"name": "Latency (ms)", "id": "latency_ms"},
                            {"name": "Active", "id": "is_active"}
                        ],
                        data=circuits,
                        style_cell={
                            "backgroundColor": self.COLORS["bg_secondary"],
                            "color": self.COLORS["text_primary"],
                            "textAlign": "left",
                            "cursor": "pointer",
                            "border": f"1px solid {self.COLORS['bg_border']}",
                            "padding": "8px"
                        },
                        style_header={
                            "backgroundColor": self.COLORS["bg_card"],
                            "fontWeight": "bold",
                            "borderBottom": f"2px solid {self.COLORS['primary']}"
                        },
                        page_size=10,
                        row_selectable="single"
                    )
                ])
            ], className="mb-4"),
            
            # Primary vs Secondary Comparison
            dbc.Card([
                dbc.CardHeader("Primary vs Secondary Comparison"),
                dbc.CardBody(id="primary-secondary-comparison")
            ])
        ])
    
    def _build_circuit_drilldown(self, circuit_id: str, data: Dict) -> html.Div:
        """Build circuit drilldown view with time series."""
        time_series = data.get("circuit_timeseries", {}).get(circuit_id, [])
        
        return html.Div([
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(f"Circuit: {circuit_id} - Time Series"),
                        dbc.CardBody([
                            dcc.Graph(
                                id="circuit-timeseries-chart",
                                figure=self._build_circuit_timeseries_chart(time_series)
                            )
                        ])
                    ])
                ], width=8),
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader("Circuit Details"),
                        dbc.CardBody(id="circuit-details")
                    ])
                ], width=4)
            ])
        ])
    
    def _build_circuit_timeseries_chart(self, time_series: List[Dict]) -> go.Figure:
        """Build time series chart for circuit metrics."""
        fig = make_subplots(
            rows=3, cols=1,
            shared_xaxes=True,
            subplot_titles=("Utilization %", "Latency (ms)", "Availability %"),
            vertical_spacing=0.08
        )
        
        if time_series:
            timestamps = [t.get("timestamp") for t in time_series]
            utilization = [t.get("utilization_pct", 0) for t in time_series]
            latency = [t.get("latency_ms", 0) for t in time_series]
            availability = [t.get("availability_pct", 100) for t in time_series]
            
            fig.add_trace(
                go.Scatter(x=timestamps, y=utilization, mode="lines", name="Utilization", line=dict(color=self.COLORS["info"])),
                row=1, col=1
            )
            
            fig.add_trace(
                go.Scatter(x=timestamps, y=latency, mode="lines", name="Latency", line=dict(color=self.COLORS["warning"])),
                row=2, col=1
            )
            
            fig.add_trace(
                go.Scatter(x=timestamps, y=availability, mode="lines", name="Availability", line=dict(color=self.COLORS["healthy"])),
                row=3, col=1
            )
            
            # Add threshold lines for utilization
            fig.add_hline(y=70, line_dash="dash", line_color=self.COLORS["warning"], row="1", col="1")
            fig.add_hline(y=90, line_dash="dash", line_color=self.COLORS["critical"], row="1", col="1")
        
        fig.update_layout(
            template="plotly_dark",
            height=500,
            showlegend=False,
            margin=dict(l=40, r=20, t=40, b=40)
        )
        
        return fig
    
    def _register_callbacks(self):
        """Register all dashboard callbacks including drilldowns and exports."""
        
        @self.app.callback(
            [
                Output("last-updated", "children"),
                Output("total-sites", "children"),
                Output("healthy-sites", "children"),
                Output("degraded-sites", "children"),
                Output("critical-sites", "children"),
                Output("active-failovers", "children"),
                Output("active-alerts", "children"),
                Output("top-congested-table", "data"),
                Output("alerts-list", "children"),
                Output("utilization-chart", "figure"),
                Output("region-chart", "figure"),
                Output("trends-chart", "figure")
            ],
            [Input("refresh-interval", "n_intervals")]
        )
        def update_dashboard(n_intervals):
            """Update all dashboard components."""
            now = datetime.now(timezone.utc)
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
            
            # CRITICAL: Require data provider - no sample data fallback
            if not self.data_provider:
                raise ValueError(
                    "Dashboard requires a data provider with real data. "
                    "Pass data_provider when creating WANPerformanceDashboard."
                )
            
            data = self.data_provider.get_dashboard_data()
            
            # Overview counts
            total_sites = data.get("total_sites", 0)
            healthy = data.get("healthy_sites", 0)
            degraded = data.get("degraded_sites", 0)
            critical = data.get("critical_sites", 0)
            failovers = data.get("active_failovers", 0)
            alerts = data.get("alert_count", 0)
            
            # Top congested table
            congested_data = data.get("top_congested", [])
            
            # Alerts list
            alerts_list = self._build_alerts_list(data.get("alerts", []))
            
            # Charts
            util_chart = self._build_utilization_chart(data.get("utilization_dist", {}))
            region_chart = self._build_region_chart(data.get("region_summary", []))
            trends_chart = self._build_trends_chart(data.get("trends", []))
            
            return [
                f"Last updated: {timestamp}",
                str(total_sites),
                str(healthy),
                str(degraded),
                str(critical),
                str(failovers),
                str(alerts),
                congested_data,
                alerts_list,
                util_chart,
                region_chart,
                trends_chart
            ]
        
        # Breadcrumb navigation callback
        @self.app.callback(
            Output("breadcrumb-nav", "children"),
            [Input("drilldown-state", "data")]
        )
        def update_breadcrumb(state):
            """Update breadcrumb navigation based on drilldown state."""
            level = state.get("level", "overview")
            
            items: List[Any] = [
                dbc.Button("Overview", id="nav-overview", color="link", className="p-0")
            ]
            
            if level in ("region", "site", "circuit"):
                items.append(html.Span(" > ", className="text-muted"))
                items.append(dbc.Button(
                    state.get("region", "Region"),
                    id="nav-region",
                    color="link",
                    className="p-0"
                ))
            
            if level in ("site", "circuit"):
                items.append(html.Span(" > ", className="text-muted"))
                items.append(dbc.Button(
                    state.get("site_name", state.get("site", "Site")),
                    id="nav-site",
                    color="link",
                    className="p-0"
                ))
            
            if level == "circuit":
                items.append(html.Span(" > ", className="text-muted"))
                items.append(html.Span(state.get("circuit", "Circuit"), className="text-primary"))
            
            return html.Div(items)
        
        # Region chart click handler for drilldown
        @self.app.callback(
            Output("drilldown-state", "data", allow_duplicate=True),
            [Input("region-chart", "clickData")],
            [State("drilldown-state", "data")],
            prevent_initial_call=True
        )
        def handle_region_click(click_data, current_state):
            """Handle click on region chart to drill down."""
            if click_data is None:
                raise PreventUpdate
            
            region = click_data["points"][0].get("x")
            if region:
                return {"level": "region", "region": region, "site": None, "circuit": None}
            
            raise PreventUpdate
        
        # Table row click handler for drilldown
        @self.app.callback(
            Output("drilldown-state", "data", allow_duplicate=True),
            [Input("top-congested-table", "selected_rows")],
            [State("top-congested-table", "data"), State("drilldown-state", "data")],
            prevent_initial_call=True
        )
        def handle_table_click(selected_rows, table_data, current_state):
            """Handle click on table row to drill down to site."""
            if not selected_rows or not table_data:
                raise PreventUpdate
            
            row = table_data[selected_rows[0]]
            site_id = row.get("site_id")
            site_name = row.get("site_name")
            region = row.get("region")
            
            if site_id:
                return {
                    "level": "site",
                    "region": region,
                    "site": site_id,
                    "site_name": site_name,
                    "circuit": None
                }
            
            raise PreventUpdate
        
        # CSV Export callbacks
        @self.app.callback(
            Output("download-congested-csv", "data"),
            [Input("export-congested-btn", "n_clicks")],
            [State("top-congested-table", "data")],
            prevent_initial_call=True
        )
        def export_congested_csv(n_clicks, data):
            """Export top congested circuits to CSV."""
            if not n_clicks or not data:
                raise PreventUpdate
            
            return self._generate_csv_download(
                data,
                "top_congested_circuits.csv",
                ["rank", "site_name", "site_id", "circuit_id", "region", "metric_value", "threshold_status"]
            )
        
        @self.app.callback(
            Output("download-alerts-csv", "data"),
            [Input("export-alerts-btn", "n_clicks")],
            prevent_initial_call=True
        )
        def export_alerts_csv(n_clicks):
            """Export active alerts to CSV."""
            if not n_clicks:
                raise PreventUpdate
            
            if not self.data_provider:
                raise ValueError("Dashboard requires a data provider with real data.")
            
            data = self.data_provider.get_dashboard_data()
            
            alerts = data.get("alerts", [])
            
            return self._generate_csv_download(
                alerts,
                "active_alerts.csv",
                ["severity", "site_name", "circuit_id", "message", "timestamp"]
            )
    
    def _generate_csv_download(
        self,
        data: List[Dict],
        filename: str,
        columns: List[str]
    ) -> Dict:
        """
        Generate CSV download data.
        
        Args:
            data: List of dictionaries to export
            filename: Output filename
            columns: Column names to include
        
        Returns:
            Dictionary for dcc.Download component
        """
        if not data:
            return {"content": "", "filename": filename}
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(data)
        
        return {
            "content": output.getvalue(),
            "filename": filename,
            "type": "text/csv"
        }
    
    def _build_alerts_list(self, alerts: List[Dict]) -> html.Div:
        """Build the alerts list component."""
        if not alerts:
            return html.Div(html.P("No active alerts", className="text-muted"))
        
        # Map numeric severity values to string labels
        severity_map = {
            1: "info",
            2: "warning",
            3: "high",
            4: "critical"
        }
        
        alert_items = []
        for alert in alerts[:10]:
            severity_value = alert.get("severity", 1)
            # Convert numeric severity to string if needed
            if isinstance(severity_value, int):
                severity = severity_map.get(severity_value, "info")
            else:
                severity = str(severity_value).lower()
            
            color = self.COLORS.get(severity, self.COLORS["info"])
            
            alert_items.append(
                dbc.Alert([
                    html.Strong(f"[{severity.upper()}] "),
                    f"{alert.get('site_name', 'Unknown')} - {alert.get('circuit_id', '')}: ",
                    alert.get("message", "")
                ], color="danger" if severity == "critical" else "warning", className="mb-2 py-2")
            )
        
        return html.Div(alert_items)
    
    def _build_utilization_chart(self, distribution: Dict) -> go.Figure:
        """Build utilization distribution chart."""
        if not distribution:
            distribution = {"0-50%": 0, "50-70%": 0, "70-80%": 0, "80-90%": 0, "90-100%": 0}
        
        colors = ["#28a745", "#6c757d", "#ffc107", "#fd7e14", "#dc3545"]
        
        fig = go.Figure(data=[
            go.Bar(
                x=list(distribution.keys()),
                y=list(distribution.values()),
                marker_color=colors
            )
        ])
        
        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title="Utilization Range",
            yaxis_title="Circuit Count"
        )
        
        return fig
    
    def _build_region_chart(self, region_data: List[Dict]) -> go.Figure:
        """Build region summary chart (clickable for drilldown)."""
        if not region_data:
            region_data = [{"region": "No Data", "avg_utilization": 0, "circuit_count": 0}]
        
        fig = go.Figure(data=[
            go.Bar(
                x=[r.get("region", "Unknown") for r in region_data],
                y=[r.get("avg_utilization", 0) for r in region_data],
                marker_color=[
                    self.COLORS["critical"] if r.get("avg_utilization", 0) >= 80
                    else self.COLORS["warning"] if r.get("avg_utilization", 0) >= 70
                    else self.COLORS["healthy"]
                    for r in region_data
                ],
                hovertemplate="<b>%{x}</b><br>Avg Utilization: %{y:.1f}%<br><extra></extra>"
            )
        ])
        
        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title="Region (click to drill down)",
            yaxis_title="Avg Utilization %"
        )
        
        return fig
    
    def _build_trends_chart(self, trends: List[Dict]) -> go.Figure:
        """Build trends line chart."""
        fig = go.Figure()
        
        if trends:
            timestamps = [t.get("timestamp") for t in trends]
            avg_util = [t.get("avg_utilization", 0) for t in trends]
            max_util = [t.get("max_utilization", 0) for t in trends]
            
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=avg_util,
                mode="lines",
                name="Avg Utilization",
                line=dict(color=self.COLORS["healthy"])
            ))
            
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=max_util,
                mode="lines",
                name="Max Utilization",
                line=dict(color=self.COLORS["warning"])
            ))
            
            fig.add_hline(y=70, line_dash="dash", line_color=self.COLORS["warning"], annotation_text="70%")
            fig.add_hline(y=80, line_dash="dash", line_color=self.COLORS["high"], annotation_text="80%")
            fig.add_hline(y=90, line_dash="dash", line_color=self.COLORS["critical"], annotation_text="90%")
        
        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=40, r=20, t=20, b=40),
            xaxis_title="Time",
            yaxis_title="Utilization %",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        
        return fig
    
    def run(self, host: str = "127.0.0.1", port: int = 8050, debug: bool = False):
        """
        Run the dashboard server.
        
        Args:
            host: Host address to bind
            port: Port number
            debug: Enable debug mode
        """
        logger.info(f"[...] Starting dashboard on http://{host}:{port}")
        
        # Dash 3.x uses app.run() instead of app.run_server()
        self.app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
