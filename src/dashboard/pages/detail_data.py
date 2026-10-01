"""
Data shaping helpers for gateway, port, and VPN peer detail pages.

These functions keep Dash callbacks thin and make the page behavior testable
without a live Mist API or Redis cache.
"""

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, unquote

import plotly.graph_objects as go
from dash import dcc
from plotly.subplots import make_subplots

from src.dashboard.pages.gateway import GatewayPage
from src.dashboard.pages.port import PortPage
from src.dashboard.pages.shared import COLORS, ChartBuilders
from src.dashboard.pages.vpn_peer import VPNPeerPage

logger = logging.getLogger(__name__)


EMPTY = "-"


def _first(record: dict[str, Any] | None, *keys: str, default: Any = None) -> Any:
    if not record:
        return default
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _fmt_num(value: Any, decimals: int = 1, default: str = EMPTY) -> str:
    if value is None or value == "":
        return default
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_int(value: Any, default: str = EMPTY) -> str:
    if value is None or value == "":
        return default
    try:
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_bps(value: Any) -> str:
    return _fmt_num(_as_float(value) / 1_000_000, 1, "0.0")


def _fmt_bytes(value: Any) -> str:
    return PortPage.format_bytes(_as_int(value, 0))


def _fmt_timestamp(value: Any) -> str:
    if value in (None, ""):
        return EMPTY
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    return str(value)


def _badge(status: str) -> dict[str, str]:
    normalized = (status or "unknown").lower()
    if normalized in {"up", "online", "connected", "true", "ok", "healthy"}:
        css = "badge bg-success"
        label = "Up"
    elif normalized in {"down", "offline", "disconnected", "false", "critical"}:
        css = "badge bg-danger"
        label = "Down"
    elif normalized in {"degraded", "warning"}:
        css = "badge bg-warning text-dark"
        label = "Degraded"
    else:
        css = "badge bg-secondary"
        label = status or "Unknown"
    return {"text": label, "className": css}


def _site_name(provider: Any, site_id: str | None) -> str:
    if not site_id:
        return EMPTY
    lookup = getattr(provider, "site_lookup", {}) or {}
    if site_id in lookup:
        return lookup[site_id]  # type: ignore[no-any-return]  # untyped third-party or cache data boundary
    for site in getattr(provider, "sites", []) or []:
        if isinstance(site, dict):
            if site.get("id") == site_id or site.get("site_id") == site_id:
                return site.get("name") or site.get("site_name") or site_id
        elif getattr(site, "site_id", None) == site_id:
            return getattr(site, "site_name", site_id)
    return site_id


def _gateway_inventory(provider: Any) -> list[dict[str, Any]]:
    for attr in ("gateways", "gateway_inventory"):
        value = getattr(provider, attr, None)
        if isinstance(value, dict):
            return list(value.get("gateways", []))
        if isinstance(value, list):
            return value
    cache = getattr(provider, "redis_cache", None)
    if cache and hasattr(cache, "get_gateway_inventory"):
        inventory = cache.get_gateway_inventory() or {}
        return list(inventory.get("gateways", []))
    return []


def _gateway_matches(gateway: dict[str, Any], gateway_id: str) -> bool:
    candidates = {
        str(_first(gateway, "id", "gateway_id", "device_id", default="")),
        str(_first(gateway, "mac", "device_mac", default="")),
    }
    normalized = gateway_id.lower().replace(":", "")
    return any(
        candidate and candidate.lower().replace(":", "") == normalized for candidate in candidates
    )


def _find_gateway(provider: Any, gateway_id: str) -> dict[str, Any] | None:
    for gateway in _gateway_inventory(provider):
        if _gateway_matches(gateway, gateway_id):
            return gateway
    return None


def _site_port_records(provider: Any, site_id: str | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for attr in ("port_stats", "ports"):
        value = getattr(provider, attr, None)
        if isinstance(value, dict):
            value = value.get(site_id, value.get("port_stats", []))
        if isinstance(value, list):
            records.extend(value)

    cache = getattr(provider, "redis_cache", None)
    if cache and site_id and hasattr(cache, "get_site_port_stats"):
        cached = cache.get_site_port_stats(site_id) or {}
        records.extend(cached.get("port_stats", []))
    if cache and site_id and hasattr(cache, "get_all_site_port_stats"):
        records.extend(cache.get_all_site_port_stats([site_id]) or [])

    if site_id:
        records = [
            port for port in records if not port.get("site_id") or port.get("site_id") == site_id
        ]

    unique: dict[tuple, dict[str, Any]] = {}
    for port in records:
        key = (port.get("site_id"), port.get("mac"), port.get("port_id") or port.get("name"))
        unique[key] = port
    return list(unique.values())


def _port_matches(port: dict[str, Any], port_id: str, gateway_id: str | None = None) -> bool:
    names = {str(_first(port, "port_id", "name", "interface", default=""))}
    if port_id not in names:
        return False
    if not gateway_id:
        return True
    gateway_hint = _first(port, "gateway_id", "device_id")
    if not gateway_hint:
        return True
    candidates = {str(gateway_hint)}
    normalized = gateway_id.lower().replace(":", "")
    return any(
        candidate and candidate.lower().replace(":", "") == normalized for candidate in candidates
    )


def _find_port(
    provider: Any,
    site_id: str | None,
    port_id: str,
    gateway_id: str | None = None,
) -> dict[str, Any] | None:
    for port in _site_port_records(provider, site_id):
        if _port_matches(port, port_id, gateway_id):
            return port
    return None


def _gateway_ports(
    provider: Any,
    site_id: str | None,
    gateway_id: str,
    gateway: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    gateway_mac = _first(gateway, "mac", "device_mac", default=gateway_id)
    ports = []
    for port in _site_port_records(provider, site_id):
        if _first(port, "mac", "device_mac", "gateway_id", "device_id", default="") in {
            gateway_id,
            gateway_mac,
        }:
            ports.append(port)
    return ports


def _site_vpn_peers(provider: Any, site_id: str | None) -> list[dict[str, Any]]:
    peers: list[dict[str, Any]] = []
    for attr in ("vpn_peers", "peers"):
        value = getattr(provider, attr, None)
        if isinstance(value, dict):
            value = value.get(site_id, value.get("peers", []))
        if isinstance(value, list):
            peers.extend(value)

    if not peers and site_id and hasattr(provider, "get_site_vpn_peers"):
        peers.extend(provider.get_site_vpn_peers(site_id) or [])
    if not peers and site_id and hasattr(provider, "get_vpn_peer_table_data"):
        peers.extend(provider.get_vpn_peer_table_data(site_id) or [])

    if site_id:
        peers = [
            peer for peer in peers if not peer.get("site_id") or peer.get("site_id") == site_id
        ]

    unique: dict[tuple, dict[str, Any]] = {}
    for peer in peers:
        key = (
            peer.get("site_id"),
            _first(peer, "peer_id", "peer_mac", "mac", "peer_router_name", default=""),
            peer.get("port_id"),
        )
        unique[key] = peer
    return list(unique.values())


def _peer_id(peer: dict[str, Any]) -> str:
    return str(
        _first(peer, "peer_id", "peer_mac", "mac", "peer_router_name", "peer_name", default="")
    )


def _find_peer(provider: Any, site_id: str | None, peer_id: str) -> dict[str, Any] | None:
    normalized = peer_id.lower().replace(":", "")
    for peer in _site_vpn_peers(provider, site_id):
        candidates = {
            _peer_id(peer),
            str(_first(peer, "peer_port_id", "vpn_name", default="")),
        }
        if any(
            candidate and candidate.lower().replace(":", "") == normalized
            for candidate in candidates
        ):
            return peer
    return None


def _call_timeseries(method: Any, **kwargs: Any) -> list[dict[str, Any]]:
    try:
        return method(**kwargs) or []
    except TypeError:
        compact = {
            key: value
            for key, value in kwargs.items()
            if key not in {"start_time", "end_time", "interval"}
        }
        return method(**compact) or []


def _time_bounds(hours: int) -> dict[str, int]:
    end_time = int(datetime.now(UTC).timestamp())
    return {"start_time": end_time - int(hours or 24) * 3600, "end_time": end_time}


def _gateway_bandwidth(
    provider: Any, site_id: str | None, gateway_id: str, ports: list[dict[str, Any]]
) -> go.Figure:
    if not provider or not site_id or not hasattr(provider, "get_gateway_port_timeseries"):
        return ChartBuilders.build_empty_chart("No gateway bandwidth data available")

    totals: dict[Any, dict[str, Any]] = {}
    bounds = _time_bounds(24)
    for port in ports or [{"mac": gateway_id, "port_id": ""}]:
        device_mac = _first(port, "mac", "device_mac", default=gateway_id)
        port_id = _first(port, "port_id", "name", default="")
        for point in _call_timeseries(
            provider.get_gateway_port_timeseries,
            site_id=site_id,
            device_mac=device_mac,
            port_id=port_id,
            **bounds,
        ):
            ts = point.get("timestamp")
            row = totals.setdefault(ts, {"timestamp": ts, "rx_bps": 0, "tx_bps": 0})
            row["rx_bps"] += _as_float(point.get("rx_bps"))
            row["tx_bps"] += _as_float(point.get("tx_bps"))
    return ChartBuilders.build_bandwidth_timeseries(list(totals.values()), "Gateway Bandwidth")


def _device_metrics(
    provider: Any, site_id: str | None, gateway_id: str, gateway: dict[str, Any] | None
) -> go.Figure:
    if not provider or not site_id or not hasattr(provider, "get_device_metrics_timeseries"):
        return ChartBuilders.build_empty_chart("No device metrics data available")

    device_mac = _first(gateway, "mac", "device_mac", default=gateway_id)
    bounds = _time_bounds(24)
    series: dict[str, list[dict[str, Any]]] = {}
    for metric in ("cpu", "memory"):
        series[metric] = _call_timeseries(
            provider.get_device_metrics_timeseries,
            site_id=site_id,
            device_mac=device_mac,
            metric=metric,
            **bounds,
        )

    if not series["cpu"] and not series["memory"]:
        return ChartBuilders.build_empty_chart("No device metrics data available")

    fig = make_subplots(specs=[[{"secondary_y": False}]])
    for metric, color in (("cpu", COLORS["warning"]), ("memory", COLORS["info"])):
        points = series[metric]
        fig.add_trace(
            go.Scatter(
                x=[datetime.fromtimestamp(_as_float(p.get("timestamp")), tz=UTC) for p in points],
                y=[
                    _as_float(_first(p, metric, "value", f"{metric}_pct", default=0))
                    for p in points
                ],
                mode="lines",
                name=metric.upper(),
                line={"color": color, "width": 2},
            )
        )
    fig.update_layout(
        template="plotly_dark",
        margin={"l": 50, "r": 20, "t": 40, "b": 40},
        title={"text": "Device Metrics", "font": {"size": 14}},
        yaxis_title="Percent",
        hovermode="x unified",
    )
    return fig


def shape_gateway_detail(provider: Any, context: dict[str, Any] | None) -> dict[str, Any]:
    gateway_id = (context or {}).get("gateway_id", "")
    site_id = (context or {}).get("site_id")
    if not provider:
        return _gateway_empty(gateway_id, site_id, "No data provider is configured")
    try:
        gateway = _find_gateway(provider, gateway_id)
        if gateway and not site_id:
            site_id = _first(gateway, "site_id")
        ports = _gateway_ports(provider, site_id, gateway_id, gateway)
        peers = _site_vpn_peers(provider, site_id) if gateway else []
        if gateway and peers:
            gateway_mac = _first(gateway, "mac", "device_mac", default=gateway_id)
            peers = [
                peer
                for peer in peers
                if _first(peer, "mac", "device_mac", "gateway_id", default=gateway_mac)
                in {gateway_id, gateway_mac}
            ] or peers
        if not gateway and not ports and not peers:
            return _gateway_empty(gateway_id, site_id, "No data for this gateway yet")

        status = _first(gateway, "status", default=None)
        if not gateway:
            status = "Unknown"
        elif status is None:
            status = "connected" if _first(gateway, "connected", default=False) else "disconnected"
        badge = _badge(str(status))
        ports_up = sum(1 for port in ports if _first(port, "up", "connected", default=True))
        ports_down = sum(1 for port in ports if not _first(port, "up", "connected", default=True))
        wan_rows = [
            GatewayPage.format_wan_port_row(site_id or "", port, gateway_id) for port in ports
        ]
        peer_rows = [_format_gateway_peer_row(site_id or "", peer) for peer in peers]

        return {
            "message": "",
            "gateway_name": _first(
                gateway, "name", "hostname", "mac", default=gateway_id[:8] + "..."
            ),
            "site_name": _site_name(provider, site_id),
            "status": badge["text"],
            "status_class": badge["className"],
            "last_seen": f"Last seen: {_fmt_timestamp(_first(gateway, 'last_seen', 'last_seen_ts', 'timestamp'))}",
            "ports_up": str(ports_up),
            "ports_down": str(ports_down),
            "vpn_peers": str(len(peers)),
            "cpu_pct": _fmt_num(_first(gateway, "cpu", "cpu_pct"), 1),
            "memory_pct": _fmt_num(_first(gateway, "memory", "memory_pct"), 1),
            "uptime": _first(gateway, "uptime", default=EMPTY),
            "wan_ports": wan_rows,
            "vpn_peer_rows": peer_rows,
            "bandwidth_figure": _gateway_bandwidth(provider, site_id, gateway_id, ports),
            "device_metrics_figure": _device_metrics(provider, site_id, gateway_id, gateway),
        }
    except Exception as error:
        logger.warning("Error shaping gateway detail page: %s", error)
        return _gateway_empty(gateway_id, site_id, "Unable to load gateway data")


def _gateway_empty(gateway_id: str, site_id: str | None, message: str) -> dict[str, Any]:
    return {
        "message": message,
        "gateway_name": gateway_id[:8] + "..." if gateway_id else EMPTY,
        "site_name": site_id or EMPTY,
        "status": "Unknown",
        "status_class": "badge bg-secondary",
        "last_seen": message,
        "ports_up": "0",
        "ports_down": "0",
        "vpn_peers": "0",
        "cpu_pct": EMPTY,
        "memory_pct": EMPTY,
        "uptime": EMPTY,
        "wan_ports": [],
        "vpn_peer_rows": [],
        "bandwidth_figure": ChartBuilders.build_empty_chart(message),
        "device_metrics_figure": ChartBuilders.build_empty_chart(message),
    }


def _format_gateway_peer_row(site_id: str, peer: dict[str, Any]) -> dict[str, Any]:
    peer_id = _peer_id(peer) or "unknown"
    peer_name = _first(
        peer, "peer_name", "peer_site_name", "peer_router_name", "vpn_name", default=peer_id
    )
    encoded_peer_id = quote(peer_id, safe="")
    return {
        "peer_name": f"[{peer_name}](/vpn/{site_id}/{encoded_peer_id})",
        "path_status": _first(
            peer, "path_status", "status", default="Up" if peer.get("up") else "Down"
        ),
        "loss_pct": _fmt_num(_first(peer, "loss", "loss_pct"), 2, "0.00"),
        "latency_ms": _fmt_num(_first(peer, "latency", "latency_ms"), 1, "0.0"),
        "jitter_ms": _fmt_num(_first(peer, "jitter", "jitter_ms"), 1, "0.0"),
        "mos_score": _fmt_num(_first(peer, "mos", "mos_score"), 2, "0.00"),
    }


def shape_port_detail(
    provider: Any, context: dict[str, Any] | None, hours: int = 24
) -> dict[str, Any]:
    site_id = (context or {}).get("site_id")
    port_id = unquote((context or {}).get("port_id", ""))
    gateway_id = (context or {}).get("gateway_id")
    if not provider:
        return _port_empty(site_id, port_id, gateway_id, "No data provider is configured")
    try:
        port = _find_port(provider, site_id, port_id, gateway_id)
        if not port:
            return _port_empty(site_id, port_id, gateway_id, "No data for this port yet")
        gateway_id = gateway_id or _first(port, "gateway_id", "mac", "device_mac")
        up = _first(port, "up", "connected", default=None)
        status = _first(port, "status", default="Up" if up else "Down")
        badge = _badge(str(status))
        util = _as_float(_first(port, "utilization_pct", "utilization", default=0))
        speed = _first(port, "speed_mbps", "speed", default=EMPTY)
        rx_bps = _first(port, "rx_bps", default=0)
        tx_bps = _first(port, "tx_bps", default=0)

        return {
            "message": "",
            "port_name": _first(port, "name", "port_id", default=port_id),
            "site_name": _site_name(provider, site_id),
            "gateway_link": (
                dcc.Link(str(gateway_id), href=f"/gateway/{gateway_id}?site_id={site_id}")
                if gateway_id
                else EMPTY
            ),
            "status": badge["text"],
            "status_class": badge["className"],
            "last_updated": f"Last updated: {_fmt_timestamp(_first(port, 'last_updated', 'timestamp'))}",
            "speed": str(speed),
            "rx_mbps": _fmt_bps(rx_bps),
            "tx_mbps": _fmt_bps(tx_bps),
            "util_pct": _fmt_num(util, 1, "0.0"),
            "rx_errors": _fmt_int(_first(port, "rx_errors", "rx_err_count", default=0), "0"),
            "tx_errors": _fmt_int(_first(port, "tx_errors", "tx_err_count", default=0), "0"),
            "utilization_gauge": ChartBuilders.build_utilization_gauge(util, "Port Utilization"),
            "rx_bytes": _fmt_bytes(_first(port, "rx_bytes", default=0)),
            "tx_bytes": _fmt_bytes(_first(port, "tx_bytes", default=0)),
            "rx_packets": _fmt_int(_first(port, "rx_pkts", "rx_packets", default=0), "0"),
            "tx_packets": _fmt_int(_first(port, "tx_pkts", "tx_packets", default=0), "0"),
            "mtu": _fmt_int(_first(port, "mtu"), EMPTY),
            "type": _first(port, "type", "port_type", default=EMPTY),
            "role": _first(port, "role", "port_usage", default=EMPTY),
            "provider": _first(port, "provider", "isp", default=EMPTY),
            "ip": _first(port, "ip", "ip_address", default=EMPTY),
            "mac": _first(port, "mac", "device_mac", default=EMPTY),
            "bandwidth_figure": _port_bandwidth(provider, site_id, port, hours),
            "rx_unicast": _fmt_int(_first(port, "rx_unicast", default=0), "0"),
            "tx_unicast": _fmt_int(_first(port, "tx_unicast", default=0), "0"),
            "rx_multicast": _fmt_int(_first(port, "rx_multicast", default=0), "0"),
            "tx_multicast": _fmt_int(_first(port, "tx_multicast", default=0), "0"),
            "rx_broadcast": _fmt_int(_first(port, "rx_broadcast", default=0), "0"),
            "tx_broadcast": _fmt_int(_first(port, "tx_broadcast", default=0), "0"),
            "rx_err_count": _fmt_int(_first(port, "rx_errors", "rx_err_count", default=0), "0"),
            "tx_err_count": _fmt_int(_first(port, "tx_errors", "tx_err_count", default=0), "0"),
            "rx_drops": _fmt_int(_first(port, "rx_drops", default=0), "0"),
            "tx_drops": _fmt_int(_first(port, "tx_drops", default=0), "0"),
            "rx_crc": _fmt_int(_first(port, "rx_crc", "rx_crc_errors", default=0), "0"),
            "tx_crc": _fmt_int(_first(port, "tx_crc", "tx_crc_errors", default=0), "0"),
        }
    except Exception as error:
        logger.warning("Error shaping port detail page: %s", error)
        return _port_empty(site_id, port_id, gateway_id, "Unable to load port data")


def _port_empty(
    site_id: str | None, port_id: str, gateway_id: str | None, message: str
) -> dict[str, Any]:
    return {
        "message": message,
        "port_name": port_id or EMPTY,
        "site_name": site_id or EMPTY,
        "gateway_link": gateway_id or EMPTY,
        "status": message,
        "status_class": "badge bg-secondary",
        "last_updated": message,
        "speed": EMPTY,
        "rx_mbps": "0.0",
        "tx_mbps": "0.0",
        "util_pct": "0.0",
        "rx_errors": "0",
        "tx_errors": "0",
        "utilization_gauge": ChartBuilders.build_utilization_gauge(0, "Port Utilization"),
        "rx_bytes": EMPTY,
        "tx_bytes": EMPTY,
        "rx_packets": EMPTY,
        "tx_packets": EMPTY,
        "mtu": EMPTY,
        "type": EMPTY,
        "role": EMPTY,
        "provider": EMPTY,
        "ip": EMPTY,
        "mac": EMPTY,
        "bandwidth_figure": ChartBuilders.build_empty_chart(message),
        "rx_unicast": EMPTY,
        "tx_unicast": EMPTY,
        "rx_multicast": EMPTY,
        "tx_multicast": EMPTY,
        "rx_broadcast": EMPTY,
        "tx_broadcast": EMPTY,
        "rx_err_count": "0",
        "tx_err_count": "0",
        "rx_drops": "0",
        "tx_drops": "0",
        "rx_crc": "0",
        "tx_crc": "0",
    }


def _port_bandwidth(
    provider: Any, site_id: str | None, port: dict[str, Any], hours: int
) -> go.Figure:
    if not provider or not site_id or not hasattr(provider, "get_gateway_port_timeseries"):
        return ChartBuilders.build_empty_chart("No bandwidth data available")
    points = _call_timeseries(
        provider.get_gateway_port_timeseries,
        site_id=site_id,
        device_mac=_first(port, "mac", "device_mac", default=""),
        port_id=_first(port, "port_id", "name", default=""),
        **_time_bounds(hours),
    )
    return ChartBuilders.build_bandwidth_timeseries(points, "Port Bandwidth")


def shape_vpn_peer_detail(
    provider: Any, context: dict[str, Any] | None, hours: int = 24
) -> dict[str, Any]:
    site_id = (context or {}).get("site_id")
    peer_id = unquote((context or {}).get("peer_id", ""))
    if not provider:
        return _vpn_empty(site_id, peer_id, "No data provider is configured")
    try:
        peer = _find_peer(provider, site_id, peer_id)
        if not peer:
            return _vpn_empty(site_id, peer_id, "No data for this VPN peer yet")
        up = _first(peer, "up", default=None)
        status = _first(peer, "path_status", "status", default="Up" if up else "Down")
        badge = _badge(str(status))
        loss = _as_float(_first(peer, "loss", "loss_pct", default=0))
        latency = _as_float(_first(peer, "latency", "latency_ms", default=0))
        jitter = _as_float(_first(peer, "jitter", "jitter_ms", default=0))
        mos = _as_float(_first(peer, "mos", "mos_score", default=0))

        return {
            "message": "",
            "peer_name": _first(peer, "peer_name", "peer_router_name", "vpn_name", default=peer_id),
            "local_site": _site_name(provider, site_id),
            "remote_site": _first(
                peer, "peer_site_name", "remote_site_name", "peer_router_name", default=EMPTY
            ),
            "status": badge["text"],
            "status_class": badge["className"],
            "last_updated": f"Last updated: {_fmt_timestamp(_first(peer, 'last_updated', 'timestamp'))}",
            "path_status": badge["text"],
            "loss_pct": _fmt_num(loss, 2, "0.00"),
            "latency_ms": _fmt_num(latency, 1, "0.0"),
            "jitter_ms": _fmt_num(jitter, 1, "0.0"),
            "mos_score": _fmt_num(mos, 2, EMPTY),
            "path_mtu": _fmt_int(_first(peer, "mtu", "path_mtu"), EMPTY),
            "loss_gauge": VPNPeerPage.build_loss_gauge(loss),
            "latency_gauge": VPNPeerPage.build_latency_gauge(latency),
            "jitter_gauge": VPNPeerPage.build_jitter_gauge(jitter),
            "mos_gauge": VPNPeerPage.build_mos_gauge(mos),
            "quality_figure": _vpn_quality(provider, site_id, peer, hours),
            "peer_mac": _first(peer, "peer_mac", "mac", default=peer_id),
            "peer_ip": _first(peer, "peer_ip", "remote_ip", default=EMPTY),
            "local_ip": _first(peer, "local_ip", default=EMPTY),
            "path_type": _first(peer, "path_type", "type", default=EMPTY),
            "tunnel_name": _first(peer, "vpn_name", "tunnel_name", default=EMPTY),
            "path_uptime": _first(peer, "uptime", "path_uptime", default=EMPTY),
            "tx_bytes": _fmt_bytes(_first(peer, "tx_bytes", default=0)),
            "rx_bytes": _fmt_bytes(_first(peer, "rx_bytes", default=0)),
            "tx_packets": _fmt_int(_first(peer, "tx_pkts", "tx_packets", default=0), "0"),
            "rx_packets": _fmt_int(_first(peer, "rx_pkts", "rx_packets", default=0), "0"),
        }
    except Exception as error:
        logger.warning("Error shaping VPN peer detail page: %s", error)
        return _vpn_empty(site_id, peer_id, "Unable to load VPN peer data")


def _vpn_empty(site_id: str | None, peer_id: str, message: str) -> dict[str, Any]:
    return {
        "message": message,
        "peer_name": peer_id or EMPTY,
        "local_site": site_id or EMPTY,
        "remote_site": EMPTY,
        "status": message,
        "status_class": "badge bg-secondary",
        "last_updated": message,
        "path_status": EMPTY,
        "loss_pct": "0.00",
        "latency_ms": "0.0",
        "jitter_ms": "0.0",
        "mos_score": EMPTY,
        "path_mtu": EMPTY,
        "loss_gauge": VPNPeerPage.build_loss_gauge(0),
        "latency_gauge": VPNPeerPage.build_latency_gauge(0),
        "jitter_gauge": VPNPeerPage.build_jitter_gauge(0),
        "mos_gauge": VPNPeerPage.build_mos_gauge(0),
        "quality_figure": ChartBuilders.build_empty_chart(message),
        "peer_mac": EMPTY,
        "peer_ip": EMPTY,
        "local_ip": EMPTY,
        "path_type": EMPTY,
        "tunnel_name": EMPTY,
        "path_uptime": EMPTY,
        "tx_bytes": EMPTY,
        "rx_bytes": EMPTY,
        "tx_packets": EMPTY,
        "rx_packets": EMPTY,
    }


def _vpn_quality(provider: Any, site_id: str | None, peer: dict[str, Any], hours: int) -> go.Figure:
    if not provider or not site_id or not hasattr(provider, "get_vpn_peer_timeseries"):
        return ChartBuilders.build_empty_chart("No VPN quality data available")
    points = _call_timeseries(
        provider.get_vpn_peer_timeseries,
        site_id=site_id,
        device_mac=_first(peer, "mac", "device_mac", "gateway_mac", default=""),
        peer_mac=_first(peer, "peer_mac", "peer_id", "mac", default=""),
        **_time_bounds(hours),
    )
    return ChartBuilders.build_quality_timeseries(points, "VPN Peer Quality")
