"""
MistWANPerformance Dashboard - Shared Components

Reusable UI components used across multiple dashboard pages.
Includes navigation, status cards, chart builders, and styling constants.
"""

import logging
from datetime import UTC, datetime
from typing import Any

import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


# T-Mobile Magenta color scheme (consistent across all pages)
COLORS = {
    # Primary brand color
    "primary": "#E20074",
    "primary_hover": "#C00062",
    "primary_light": "#FF3399",
    # Status colors
    "healthy": "#28a745",
    "degraded": "#ffc107",
    "critical": "#dc3545",
    "normal": "#6c757d",
    "warning": "#ffc107",
    "high": "#fd7e14",
    "info": "#17a2b8",
    # Background colors (dark theme)
    "bg_primary": "#1a1a1a",
    "bg_secondary": "#2d2d2d",
    "bg_card": "#363636",
    "bg_border": "#404040",
    # Text colors
    "text_primary": "#e0e0e0",
    "text_secondary": "#a0a0a0",
}

# Refresh interval in milliseconds
REFRESH_INTERVAL_MS = 60000


class NavigationBar:
    """Top navigation bar with breadcrumb and back navigation."""

    @staticmethod
    def build(
        current_page: str, breadcrumbs: list[dict[str, str]], show_home: bool = True
    ) -> dbc.Navbar:
        """
        Build navigation bar with breadcrumbs.

        Args:
            current_page: Current page title
            breadcrumbs: List of {label, href} for breadcrumb trail
            show_home: Whether to show home link

        Returns:
            Bootstrap navbar component
        """
        breadcrumb_items = []

        if show_home:
            breadcrumb_items.append(
                dbc.NavItem(
                    dcc.Link(
                        "Overview",
                        href="/",
                        className="nav-link",
                        style={"color": COLORS["primary"]},
                    )
                )
            )

        for crumb in breadcrumbs:
            breadcrumb_items.append(html.Span(" > ", className="text-muted mx-2"))
            if crumb.get("href"):
                breadcrumb_items.append(
                    dbc.NavItem(
                        dcc.Link(
                            crumb["label"],
                            href=crumb["href"],
                            className="nav-link",
                            style={"color": COLORS["primary"]},
                        )
                    )
                )
            else:
                breadcrumb_items.append(html.Span(crumb["label"], className="text-light fw-bold"))

        return dbc.Navbar(
            dbc.Container(
                [
                    dbc.NavbarBrand(
                        "WAN Performance Dashboard",
                        href="/",
                        style={"color": COLORS["primary"], "fontWeight": "bold"},
                    ),
                    dbc.Nav(breadcrumb_items, className="ms-auto"),
                ],
                fluid=True,
            ),
            color="dark",
            dark=True,
            className="mb-3",
        )


class StatusCards:
    """Reusable status card components."""

    @staticmethod
    def build_card(card_id: str, title: str, value: str, status: str | None = None) -> dbc.Card:
        """
        Build a status overview card.

        Args:
            card_id: HTML ID for the card value element
            title: Card title text
            value: Initial value to display
            status: Status color key (healthy, critical, etc.)

        Returns:
            Bootstrap card component
        """
        color = COLORS.get(status, "#6c757d") if status else "#6c757d"

        return dbc.Card(
            [
                dbc.CardBody(
                    [
                        html.H4(id=card_id, children=value, style={"color": color}),
                        html.P(title, className="text-muted mb-0"),
                    ]
                )
            ],
            className="text-center",
        )

    @staticmethod
    def build_metric_card(
        title: str,
        value: str,
        subtitle: str | None = None,
        trend: str | None = None,
        status: str | None = None,
    ) -> dbc.Card:
        """
        Build a metric card with optional trend indicator.

        Args:
            title: Card title
            value: Main metric value
            subtitle: Optional subtitle text
            trend: Optional trend indicator (up, down, stable)
            status: Status color key

        Returns:
            Bootstrap card component
        """
        color = COLORS.get(status, COLORS["text_primary"])

        trend_icon = ""
        if trend == "up":
            trend_icon = " [^]"
        elif trend == "down":
            trend_icon = " [v]"
        elif trend == "stable":
            trend_icon = " [-]"

        body_children = [
            html.H3(f"{value}{trend_icon}", style={"color": color}),
            html.P(title, className="text-muted mb-0"),
        ]

        if subtitle:
            body_children.append(html.Small(subtitle, className="text-muted"))

        return dbc.Card([dbc.CardBody(body_children)], className="text-center h-100")


class ChartBuilders:
    """Reusable chart building functions."""

    @staticmethod
    def build_empty_chart(message: str = "No data available") -> go.Figure:
        """Build an empty chart with a message."""
        fig = go.Figure()
        fig.add_annotation(
            text=message,
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=14, color=COLORS["text_secondary"]),
        )
        fig.update_layout(template="plotly_dark", margin=dict(l=40, r=20, t=20, b=40))
        return fig

    @staticmethod
    def build_bandwidth_timeseries(
        timeseries_data: list[dict], title: str = "Bandwidth"
    ) -> go.Figure:
        """
        Build bandwidth time-series chart with rx/tx.

        Args:
            timeseries_data: List of {timestamp, rx_bps, tx_bps}
            title: Chart title

        Returns:
            Plotly figure
        """
        fig = go.Figure()

        if timeseries_data:
            timestamps = [
                datetime.fromtimestamp(t.get("timestamp", 0), tz=UTC)
                for t in timeseries_data
            ]
            rx_mbps = [t.get("rx_bps", 0) / 1_000_000 for t in timeseries_data]
            tx_mbps = [t.get("tx_bps", 0) / 1_000_000 for t in timeseries_data]

            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=rx_mbps,
                    mode="lines",
                    name="RX (Mbps)",
                    line=dict(color=COLORS["info"], width=2),
                    fill="tozeroy",
                    fillcolor="rgba(23, 162, 184, 0.15)",
                    hovertemplate="Time: %{x}<br>RX: %{y:.2f} Mbps<extra></extra>",
                )
            )

            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=tx_mbps,
                    mode="lines",
                    name="TX (Mbps)",
                    line=dict(color=COLORS["primary"], width=2),
                    fill="tozeroy",
                    fillcolor="rgba(226, 0, 116, 0.15)",
                    hovertemplate="Time: %{x}<br>TX: %{y:.2f} Mbps<extra></extra>",
                )
            )
        else:
            return ChartBuilders.build_empty_chart("No bandwidth data available")

        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=50, r=20, t=40, b=40),
            title=dict(text=title, font=dict(size=14)),
            xaxis_title="Time",
            yaxis_title="Bandwidth (Mbps)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
        )

        return fig

    @staticmethod
    def build_quality_timeseries(
        timeseries_data: list[dict], title: str = "Quality Metrics"
    ) -> go.Figure:
        """
        Build quality time-series chart with loss/latency/jitter.

        Args:
            timeseries_data: List of {timestamp, loss, latency, jitter}
            title: Chart title

        Returns:
            Plotly figure with dual y-axis
        """
        fig = make_subplots(specs=[[{"secondary_y": True}]])

        if timeseries_data:
            timestamps = [
                datetime.fromtimestamp(t.get("timestamp", 0), tz=UTC)
                for t in timeseries_data
            ]
            loss_pct = [t.get("loss", 0) for t in timeseries_data]
            latency_ms = [t.get("latency", 0) for t in timeseries_data]
            jitter_ms = [t.get("jitter", 0) for t in timeseries_data]

            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=loss_pct,
                    mode="lines",
                    name="Loss (%)",
                    line=dict(color=COLORS["critical"], width=2),
                    hovertemplate="Loss: %{y:.2f}%<extra></extra>",
                ),
                secondary_y=False,
            )

            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=latency_ms,
                    mode="lines",
                    name="Latency (ms)",
                    line=dict(color=COLORS["warning"], width=2),
                    hovertemplate="Latency: %{y:.1f} ms<extra></extra>",
                ),
                secondary_y=True,
            )

            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=jitter_ms,
                    mode="lines",
                    name="Jitter (ms)",
                    line=dict(color=COLORS["info"], width=2, dash="dot"),
                    hovertemplate="Jitter: %{y:.1f} ms<extra></extra>",
                ),
                secondary_y=True,
            )
        else:
            return ChartBuilders.build_empty_chart("No quality data available")

        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=50, r=50, t=40, b=40),
            title=dict(text=title, font=dict(size=14)),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified",
        )

        fig.update_yaxes(title_text="Loss (%)", secondary_y=False)
        fig.update_yaxes(title_text="Latency / Jitter (ms)", secondary_y=True)

        return fig

    @staticmethod
    def build_utilization_gauge(utilization_pct: float, title: str = "Utilization") -> go.Figure:
        """
        Build a gauge chart for utilization percentage.

        Args:
            utilization_pct: Current utilization (0-100)
            title: Gauge title

        Returns:
            Plotly gauge figure
        """
        # Determine color based on thresholds
        if utilization_pct >= 90:
            bar_color = COLORS["critical"]
        elif utilization_pct >= 80:
            bar_color = COLORS["high"]
        elif utilization_pct >= 70:
            bar_color = COLORS["warning"]
        else:
            bar_color = COLORS["healthy"]

        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=utilization_pct,
                domain={"x": [0, 1], "y": [0, 1]},
                title={"text": title, "font": {"color": COLORS["text_primary"]}},
                number={"suffix": "%", "font": {"color": COLORS["text_primary"]}},
                gauge={
                    "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": COLORS["bg_border"]},
                    "bar": {"color": bar_color},
                    "bgcolor": COLORS["bg_secondary"],
                    "borderwidth": 2,
                    "bordercolor": COLORS["bg_border"],
                    "steps": [
                        {"range": [0, 70], "color": "rgba(40, 167, 69, 0.2)"},
                        {"range": [70, 80], "color": "rgba(255, 193, 7, 0.2)"},
                        {"range": [80, 90], "color": "rgba(253, 126, 20, 0.2)"},
                        {"range": [90, 100], "color": "rgba(220, 53, 69, 0.2)"},
                    ],
                    "threshold": {
                        "line": {"color": COLORS["critical"], "width": 4},
                        "thickness": 0.75,
                        "value": 90,
                    },
                },
            )
        )

        fig.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=50, b=20), height=200)

        return fig


class LinkBuilder:
    """Build clickable links for navigation to detail pages."""

    @staticmethod
    def gateway_link(gateway_id: str, gateway_name: str, site_id: str | None = None) -> dcc.Link:
        """
        Build a clickable link to gateway detail page.

        Args:
            gateway_id: Gateway device ID
            gateway_name: Display name for the gateway
            site_id: Optional site ID for context

        Returns:
            Dash Link component
        """
        href = f"/gateway/{gateway_id}"
        if site_id:
            href += f"?site_id={site_id}"

        return dcc.Link(
            gateway_name,
            href=href,
            style={"color": COLORS["primary"], "textDecoration": "none", "cursor": "pointer"},
            className="gateway-link",
        )

    @staticmethod
    def port_link(
        site_id: str, port_id: str, port_name: str, gateway_id: str | None = None
    ) -> dcc.Link:
        """
        Build a clickable link to port detail page.

        Args:
            site_id: Site ID containing the port
            port_id: Port/interface identifier
            port_name: Display name for the port
            gateway_id: Optional gateway ID for context

        Returns:
            Dash Link component
        """
        href = f"/port/{site_id}/{port_id}"
        if gateway_id:
            href += f"?gateway_id={gateway_id}"

        return dcc.Link(
            port_name,
            href=href,
            style={"color": COLORS["info"], "textDecoration": "none", "cursor": "pointer"},
            className="port-link",
        )

    @staticmethod
    def vpn_peer_link(site_id: str, peer_id: str, peer_name: str) -> dcc.Link:
        """
        Build a clickable link to VPN peer detail page.

        Args:
            site_id: Site ID for the VPN peer
            peer_id: VPN peer path identifier
            peer_name: Display name for the peer

        Returns:
            Dash Link component
        """
        return dcc.Link(
            peer_name,
            href=f"/vpn/{site_id}/{peer_id}",
            style={"color": COLORS["warning"], "textDecoration": "none", "cursor": "pointer"},
            className="vpn-peer-link",
        )


class PageLayout:
    """Common page layout wrapper."""

    @staticmethod
    def wrap(
        page_id: str,
        title: str,
        breadcrumbs: list[dict[str, str]],
        content: list[Any],
        refresh_interval: int = REFRESH_INTERVAL_MS,
    ) -> html.Div:
        """
        Wrap page content with standard layout elements.

        Args:
            page_id: Unique page identifier
            title: Page title
            breadcrumbs: Breadcrumb trail
            content: Page content components
            refresh_interval: Auto-refresh interval in ms

        Returns:
            Complete page layout
        """
        return html.Div(
            [
                # Navigation
                NavigationBar.build(title, breadcrumbs),
                # Refresh interval
                dcc.Interval(
                    id=f"{page_id}-refresh-interval", interval=refresh_interval, n_intervals=0
                ),
                # Main content container
                dbc.Container(content, fluid=True, id=f"{page_id}-container"),
            ],
            id=page_id,
        )
