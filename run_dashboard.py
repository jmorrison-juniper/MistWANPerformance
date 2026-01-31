"""
MistWANPerformance - Dashboard Launcher

Run this script to start the NOC dashboard web interface.

Features:
- Live data from Mist API with Redis caching
- Background refresh: Continuously updates stale data (oldest first)
- No batch limits: Fetches ALL available data
- Async data loading: Dashboard starts immediately, data loads in background
- Parallel processing: Multi-core port stats processing
- Async precomputation: TaskGroup for I/O, ProcessPoolExecutor for CPU

Usage:
    python run_dashboard.py
    python run_dashboard.py --port 8080
    python run_dashboard.py --debug
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List, Tuple, Dict, Any, Optional

from src.utils.logging_config import setup_logging
from src.utils.config import Config
from src.dashboard.app import WANPerformanceDashboard
from src.dashboard.data_provider import DashboardDataProvider
from src.models.dimensions import DimSite, DimCircuit
from src.models.facts import CircuitUtilizationRecord

# Import both legacy and async precomputers
from src.cache.dashboard_precompute import DashboardPrecomputer
from src.cache.site_precompute import SiteSlePrecomputer, SiteVpnPrecomputer
from src.cache.async_precompute import (
    AsyncDashboardPrecomputer,
    AsyncSiteSlePrecomputer,
    AsyncSiteVpnPrecomputer,
    shutdown_process_pool,
)

# Global references for background refresh and data loading
_background_worker = None
_sle_background_worker = None
_vpn_peer_background_worker = None
_dashboard_precomputer = None
_site_sle_precomputer = None
_site_vpn_precomputer = None
_api_client = None
_cache = None
_data_provider = None
_data_load_thread = None
_shutdown_event = threading.Event()
_dashboard_app = None  # Store dashboard for WSGI access

# Async event loop for precomputers (runs in dedicated thread)
_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_thread: Optional[threading.Thread] = None

# CPU count for parallel processing (leave 1 core for system)
CPU_COUNT = max(1, (os.cpu_count() or 4) - 1)


def create_wsgi_app():
    """
    Create the WSGI application for production servers (Gunicorn/uWSGI).
    
    This function initializes the dashboard and returns the Flask server
    for use with WSGI servers like Gunicorn.
    
    Usage:
        gunicorn -c gunicorn_config.py "run_dashboard:create_wsgi_app()"
    
    Returns:
        Flask server instance
    """
    global _dashboard_app, _data_provider, _cache
    
    # Setup logging
    setup_logging(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("MistWANPerformance - NOC Dashboard (WSGI)")
    logger.info("=" * 60)
    
    # Load configuration
    from src.utils.config import Config
    config = Config()
    
    # Load cached data
    cached_provider, cache_instance = quick_load_from_cache(config)
    
    if cached_provider:
        _data_provider = cached_provider
        _cache = cache_instance
        logger.info("[OK] Dashboard initialized with cached data")
    else:
        _data_provider = DashboardDataProvider(sites=[], circuits=[])
        _cache = cache_instance
        logger.info("[INFO] Dashboard initialized - loading data in background")
    
    # Create dashboard
    _dashboard_app = WANPerformanceDashboard(
        app_name="WAN Performance - NOC Dashboard",
        data_provider=_data_provider
    )
    
    # Start background workers if API credentials available
    if config.mist is not None and _cache:
        try:
            from src.api.mist_client import MistAPIClient
            api_client = MistAPIClient(config.mist, config.operational)
            
            # CRITICAL: Load sites if not in cache - required for dashboard to work
            if not _data_provider.sites or len(_data_provider.site_lookup) == 0:
                logger.info("[...] Loading sites from Mist API (required for dashboard)")
                try:
                    # Load site groups first for region names
                    sitegroup_map = api_client.get_site_groups()
                    _cache.set_site_groups(sitegroup_map)
                    
                    # Load sites
                    raw_sites = api_client.get_sites()
                    _cache.set_sites(raw_sites)
                    
                    # Convert to dimension models
                    sites = []
                    for raw_site in raw_sites:
                        sitegroup_ids = raw_site.get("sitegroup_ids", [])
                        if sitegroup_ids and sitegroup_ids[0] in sitegroup_map:
                            region_name = sitegroup_map[sitegroup_ids[0]]
                        else:
                            region_name = "Unassigned"
                        
                        site = DimSite(
                            site_id=raw_site.get("id", ""),
                            site_name=raw_site.get("name", "Unknown"),
                            region=region_name,
                            timezone=raw_site.get("timezone", "UTC"),
                            address=raw_site.get("address", "")
                        )
                        sites.append(site)
                    
                    # Update data provider with sites
                    _data_provider.sites = sites
                    _data_provider.site_lookup = {s.site_id: s.site_name for s in sites}
                    _data_provider.region_lookup = {s.site_id: (s.region or "Unknown") for s in sites}
                    
                    # Also fetch and cache SLE data for background worker
                    sle_data = api_client.get_org_sites_sle()
                    if sle_data:
                        _cache.save_sle_snapshot(sle_data)
                        _data_provider.update_sle_data(sle_data)
                    
                    logger.info(f"[OK] Loaded {len(sites)} sites and SLE data from API")
                except Exception as site_error:
                    logger.error(f"[ERROR] Could not load sites: {site_error}", exc_info=True)
            
            # Fetch gateway inventory if not in cache (quick API call)
            if _data_provider.gateways_total == 0:
                logger.info("[...] Fetching gateway inventory (quick API call)")
                try:
                    gateway_inventory = api_client.get_gateway_inventory()
                    _data_provider.update_gateway_inventory(gateway_inventory)
                    _cache.save_gateway_inventory(gateway_inventory)
                    logger.info(
                        f"[OK] Gateway health: {_data_provider.gateways_connected} online, "
                        f"{_data_provider.gateways_disconnected} offline"
                    )
                except Exception as gw_error:
                    logger.warning(f"[WARN] Could not fetch gateway inventory: {gw_error}")
            
            # Start background data loading
            _start_background_workers(config, api_client, _cache, _data_provider)
            logger.info("[OK] Background workers started")
        except Exception as e:
            logger.error(f"[ERROR] Failed to start background workers: {e}")
    
    return _dashboard_app.app.server


def _start_background_workers(config, api_client, cache, data_provider):
    """Start background workers for data refresh."""
    global _background_worker, _sle_background_worker, _vpn_peer_background_worker
    
    from src.cache.background_refresh import (
        BackgroundRefreshWorker,
        SLEBackgroundWorker,
        VPNPeerBackgroundWorker,
    )
    
    logger = logging.getLogger(__name__)
    
    # Get site IDs from cache
    site_ids = []
    try:
        port_stats = cache.get_all_site_port_stats()
        if port_stats:
            site_ids = list(set(p.get("site_id") for p in port_stats if p.get("site_id")))
    except Exception:
        pass
    
    # Start port stats refresh worker
    _background_worker = BackgroundRefreshWorker(
        cache=cache,
        api_client=api_client,
        site_ids=site_ids,
        min_delay_between_fetches=5,
        max_age_seconds=3600
    )
    _background_worker.start()
    
    # Start SLE background worker
    _sle_background_worker = SLEBackgroundWorker(
        cache=cache,
        api_client=api_client,
        data_provider=data_provider,
        min_delay_between_fetches=2,
        max_age_seconds=3600
    )
    _sle_background_worker.start()
    
    # Start VPN peer background worker
    _vpn_peer_background_worker = VPNPeerBackgroundWorker(
        cache=cache,
        api_client=api_client
    )
    _vpn_peer_background_worker.start()
    
    # Start async precomputers
    start_async_precomputers(cache, data_provider)


def _run_async_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """
    Run the asyncio event loop in a dedicated thread.
    
    This allows async precomputers to run alongside the synchronous
    Dash/Flask application.
    """
    asyncio.set_event_loop(loop)
    try:
        loop.run_forever()
    finally:
        # Cleanup pending tasks
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def start_async_precomputers(cache, data_provider) -> None:
    """
    Start async precomputers in a dedicated asyncio event loop.
    
    Creates a new event loop running in a background thread,
    allowing async TaskGroup parallelization for I/O-bound work
    and ProcessPoolExecutor for CPU-bound computation.
    """
    global _async_loop, _async_thread
    global _dashboard_precomputer, _site_sle_precomputer, _site_vpn_precomputer
    
    logger = logging.getLogger(__name__)
    
    # Create new event loop for async precomputers
    _async_loop = asyncio.new_event_loop()
    
    # Create async precomputers (they will use the loop when started)
    _dashboard_precomputer = AsyncDashboardPrecomputer(
        cache=cache,
        data_provider=data_provider,
        refresh_interval=20  # 20 second cycle
    )
    
    _site_sle_precomputer = AsyncSiteSlePrecomputer(
        cache=cache,
        data_provider=data_provider,
        concurrent_sites=50,  # 50 sites in parallel
        cycle_delay=1.0
    )
    
    _site_vpn_precomputer = AsyncSiteVpnPrecomputer(
        cache=cache,
        data_provider=data_provider,
        concurrent_sites=50,  # 50 sites in parallel
        cycle_delay=1.0
    )
    
    # Schedule precomputers to start in the event loop
    def schedule_precomputers():
        _dashboard_precomputer._task = _async_loop.create_task(
            _dashboard_precomputer._precompute_loop()
        )
        _dashboard_precomputer._running = True
        
        _site_sle_precomputer._task = _async_loop.create_task(
            _site_sle_precomputer._precompute_loop()
        )
        _site_sle_precomputer._running = True
        
        _site_vpn_precomputer._task = _async_loop.create_task(
            _site_vpn_precomputer._precompute_loop()
        )
        _site_vpn_precomputer._running = True
    
    # Start the event loop in a background thread
    _async_thread = threading.Thread(
        target=_run_async_event_loop,
        args=(_async_loop,),
        daemon=True,
        name="async-precompute-loop"
    )
    _async_thread.start()
    
    # Schedule precomputers (must be done after loop starts)
    _async_loop.call_soon_threadsafe(schedule_precomputers)
    
    # Expose to data provider for status queries
    data_provider.dashboard_precomputer = _dashboard_precomputer
    data_provider.site_sle_precomputer = _site_sle_precomputer
    data_provider.site_vpn_precomputer = _site_vpn_precomputer
    
    logger.info(
        "[OK] Async precomputers started (TaskGroup I/O parallelism, "
        "ProcessPoolExecutor CPU parallelism)"
    )


def stop_async_precomputers() -> None:
    """Stop all async precomputers and shutdown the event loop."""
    global _async_loop, _async_thread
    global _dashboard_precomputer, _site_sle_precomputer, _site_vpn_precomputer
    
    logger = logging.getLogger(__name__)
    
    # Stop precomputers
    if _dashboard_precomputer:
        _dashboard_precomputer._running = False
        if _dashboard_precomputer._task:
            _async_loop.call_soon_threadsafe(_dashboard_precomputer._task.cancel)
    
    if _site_sle_precomputer:
        _site_sle_precomputer._running = False
        if _site_sle_precomputer._task:
            _async_loop.call_soon_threadsafe(_site_sle_precomputer._task.cancel)
    
    if _site_vpn_precomputer:
        _site_vpn_precomputer._running = False
        if _site_vpn_precomputer._task:
            _async_loop.call_soon_threadsafe(_site_vpn_precomputer._task.cancel)
    
    # Stop the event loop
    if _async_loop and _async_loop.is_running():
        _async_loop.call_soon_threadsafe(_async_loop.stop)
    
    # Wait for thread to finish
    if _async_thread and _async_thread.is_alive():
        _async_thread.join(timeout=5)
    
    # Shutdown process pool
    shutdown_process_pool()
    
    logger.info("[OK] Async precomputers stopped")


def calculate_utilization_pct(
    rx_bps: int,
    tx_bps: int,
    speed_mbps: int
) -> float:
    """
    Calculate utilization percentage from bits-per-second rates.
    
    Args:
        rx_bps: Received bits per second (real-time rate from Mist API)
        tx_bps: Transmitted bits per second (real-time rate from Mist API)
        speed_mbps: Port speed in Mbps
    
    Returns:
        Utilization percentage (0.0 - 100.0)
    
    Note:
        Uses rx_bps/tx_bps directly from Mist API, NOT cumulative byte counters.
        The cumulative rx_bytes/tx_bytes counters measure total traffic since boot
        and would produce wildly incorrect utilization values.
    """
    if speed_mbps <= 0:
        return 0.0
    
    # Use max of rx/tx for utilization (asymmetric traffic)
    max_bps = max(rx_bps, tx_bps)
    
    # Port speed in bps
    bandwidth_bps = speed_mbps * 1_000_000
    
    # Calculate percentage
    utilization_pct = (max_bps / bandwidth_bps) * 100
    
    # Cap at 100% (can exceed due to burst traffic)
    return min(utilization_pct, 100.0)


def load_from_cache(cache, config: Config) -> tuple:
    """
    Load data from Redis cache instead of Mist API.
    
    Uses per-site cache for granular freshness checking.
    Falls back to global port_stats cache if per-site not available.
    
    Args:
        cache: Redis cache instance
        config: Application configuration
    
    Returns:
        Tuple of (DashboardDataProvider, all_site_ids)
        
    Raises:
        ValueError: If cache is missing required data
    """
    logger = logging.getLogger(__name__)
    logger.info("[...] Loading data from Redis cache")
    
    # Load cached site groups
    sitegroup_map = cache.get_site_groups()
    if not sitegroup_map:
        sitegroup_map = {}
        logger.warning("[WARN] No site groups in cache")
    
    # Load cached sites
    raw_sites = cache.get_sites()
    if not raw_sites:
        raise ValueError("No sites in cache - cache may be corrupted")
    
    logger.info(f"[OK] Loaded {len(raw_sites)} sites from cache")
    
    # Convert to dimension models with human-readable region names
    sites = []
    for raw_site in raw_sites:
        sitegroup_ids = raw_site.get("sitegroup_ids", [])
        if sitegroup_ids and sitegroup_ids[0] in sitegroup_map:
            region_name = sitegroup_map[sitegroup_ids[0]]
        else:
            region_name = "Unassigned"
        
        site = DimSite(
            site_id=raw_site.get("id", ""),
            site_name=raw_site.get("name", "Unknown"),
            region=region_name,
            timezone=raw_site.get("timezone", "UTC"),
            address=raw_site.get("address", "")
        )
        sites.append(site)
    
    # Build site lookup
    site_lookup = {s.site_id: s for s in sites}
    all_site_ids = list(site_lookup.keys())
    
    # Try to load from per-site cache first (more granular freshness)
    port_stats = cache.get_all_site_port_stats(all_site_ids)
    
    if port_stats:
        logger.info(f"[OK] Loaded {len(port_stats)} port stats from per-site cache")
    else:
        # Fall back to global port_stats cache
        port_stats = cache.get_port_stats()
        if not port_stats:
            raise ValueError("No port stats in cache - cache may be corrupted")
        logger.info(f"[OK] Loaded {len(port_stats)} port stats from global cache")
    
    # Process port stats into utilization records (same logic as live data)
    circuits, utilization_records, wan_down, wan_disabled = process_port_stats_to_utilization(
        port_stats, site_lookup, sitegroup_map
    )
    
    if not utilization_records:
        raise ValueError("No utilization records could be created from cached data")
    
    # Create data provider with Redis cache reference for trends
    provider = DashboardDataProvider(sites=sites, circuits=circuits)
    provider.redis_cache = cache  # Enable historical trends storage/retrieval
    provider.wan_down_count = wan_down
    provider.wan_disabled_count = wan_disabled
    provider.update_utilization(utilization_records)
    
    # Store snapshot for trends history
    provider.store_snapshot_for_trends()
    
    # Load cached SLE data (if available)
    sle_data = cache.get_sle_snapshot()
    if sle_data:
        provider.update_sle_data(sle_data)
        logger.info(f"[OK] Loaded cached SLE data for {sle_data.get('total', 0)} sites")
    
    # Load cached gateway inventory for disconnected site detection
    gateway_inventory = cache.get_gateway_inventory()
    if gateway_inventory:
        provider.update_gateway_inventory(gateway_inventory)
        logger.info(
            f"[OK] Loaded cached gateway inventory: "
            f"{provider.gateways_connected} online, {provider.gateways_disconnected} offline"
        )
    
    # Load cached alarms (if available)
    alarms_data = cache.get_alarms()
    if alarms_data:
        provider.update_alarms(alarms_data)
        logger.info(f"[OK] Loaded cached alarms: {alarms_data.get('total', 0)} alarms")
    
    logger.info(f"[OK] Cached data loaded: {len(sites)} sites, {len(utilization_records)} utilization records")
    
    # Store cache reference for background refresh
    global _cache
    _cache = cache
    
    # Create API client for background refresh (even when using cache)
    global _api_client
    from src.api.mist_client import MistAPIClient
    if config.mist is None:
        raise ValueError("Mist configuration is required")
    _api_client = MistAPIClient(config.mist, config.operational)
    
    # Note: Gateway inventory is loaded at startup (main function)
    
    return provider, all_site_ids

def _process_port_batch(
    port_batch: List[Dict[str, Any]],
    site_lookup_keys: set,
    current_hour: str
) -> Tuple[List[dict], List[dict], int]:
    """
    Process a batch of port stats in parallel.
    
    This function is designed to be called from a thread pool for parallelization.
    Returns raw dicts instead of dataclass instances to avoid pickling issues.
    
    Args:
        port_batch: List of port statistics to process
        site_lookup_keys: Set of valid site_ids (for filtering)
        current_hour: Current hour key for records
    
    Returns:
        Tuple of (circuit_dicts, utilization_dicts, wan_port_count, wan_down_count, wan_disabled_count)
    """
    circuits = []
    utilization_records = []
    wan_port_count = 0
    wan_down_count = 0
    wan_disabled_count = 0
    
    for port in port_batch:
        device_type = port.get("device_type", "")
        port_usage = port.get("port_usage", "")
        port_id = port.get("port_id", "")
        
        # WAN port filtering criteria
        is_wan_port = (
            (device_type == "gateway" and port_usage == "wan") or
            port_usage == "wan" or
            port_id.startswith("lte")
        )
        
        if not is_wan_port:
            continue
        
        # Skip disabled or down ports - they should not show utilization
        is_disabled = port.get("disabled", False)
        is_up = port.get("up", True)
        if is_disabled:
            wan_disabled_count += 1
            continue
        if not is_up:
            wan_down_count += 1
            continue
        
        wan_port_count += 1
        site_id = port.get("site_id", "")
        
        # Skip if site not in lookup
        if site_id not in site_lookup_keys:
            continue
        
        device_mac = port.get("mac", "")
        rx_bps = port.get("rx_bps", 0) or 0
        tx_bps = port.get("tx_bps", 0) or 0
        rx_bytes = port.get("rx_bytes", 0) or 0
        tx_bytes = port.get("tx_bytes", 0) or 0
        speed = port.get("speed", 1000) or 1000
        
        circuit_id = f"{device_mac}:{port_id}"
        
        # Calculate utilization from real-time bps rates
        if speed > 0:
            max_bps = max(rx_bps, tx_bps)
            bandwidth_bps = speed * 1_000_000
            utilization_pct = min((max_bps / bandwidth_bps) * 100, 100.0)
        else:
            utilization_pct = 0.0
        
        # Store as dicts for thread safety
        circuits.append({
            "circuit_id": circuit_id,
            "site_id": site_id,
            "device_id": device_mac,
            "port_name": port_id,
            "bandwidth_mbps": speed,
            "provider": "Unknown",
            "circuit_type": "wan",
            "role": "primary" if "0" in port_id else "secondary"
        })
        
        utilization_records.append({
            "site_id": site_id,
            "circuit_id": circuit_id,
            "hour_key": current_hour,
            "utilization_pct": round(utilization_pct, 2),
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "bandwidth_mbps": speed
        })
    
    return circuits, utilization_records, wan_port_count, wan_down_count, wan_disabled_count


def process_port_stats_to_utilization(
    port_stats: list,
    site_lookup: dict,
    sitegroup_map: dict
) -> tuple:
    """
    Process port statistics into circuits and utilization records.
    
    Uses parallel processing for large datasets (>1000 ports).
    
    Args:
        port_stats: List of port statistics from API/cache
        site_lookup: Dictionary mapping site_id to DimSite
        sitegroup_map: Dictionary mapping sitegroup_id to name
    
    Returns:
        Tuple of (circuits list, utilization_records list, wan_down_count, wan_disabled_count)
    """
    logger = logging.getLogger(__name__)
    current_hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    
    # Log diagnostic info (sample first 500)
    port_usage_counts = {}
    device_type_counts = {}
    for port in port_stats[:500]:
        usage = port.get("port_usage", "NONE")
        device_type = port.get("device_type", "unknown")
        port_usage_counts[usage] = port_usage_counts.get(usage, 0) + 1
        device_type_counts[device_type] = device_type_counts.get(device_type, 0) + 1
    logger.info(f"[DEBUG] Port usage values in sample (500): {port_usage_counts}")
    logger.info(f"[DEBUG] Device types in sample (500): {device_type_counts}")
    
    # Count device types across ALL data
    all_device_types = {}
    for port in port_stats:
        device_type = port.get("device_type", "unknown")
        all_device_types[device_type] = all_device_types.get(device_type, 0) + 1
    logger.info(f"[INFO] Device type breakdown (all {len(port_stats)} ports): {all_device_types}")
    
    # Prepare site lookup keys for parallel processing
    site_lookup_keys = set(site_lookup.keys())
    
    # Use parallel processing for large datasets
    total_ports = len(port_stats)
    use_parallel = total_ports > 1000
    total_wan_down = 0
    total_wan_disabled = 0
    
    if use_parallel:
        # Split into batches for parallel processing
        batch_size = max(500, total_ports // CPU_COUNT)
        batches = [
            port_stats[i:i + batch_size]
            for i in range(0, total_ports, batch_size)
        ]
        
        logger.info(f"[...] Processing {total_ports} ports in {len(batches)} batches using {CPU_COUNT} threads")
        
        all_circuits = []
        all_utilization_records = []
        total_wan_count = 0
        
        # Use ThreadPoolExecutor (ProcessPoolExecutor has pickling overhead)
        with ThreadPoolExecutor(max_workers=CPU_COUNT) as executor:
            futures = [
                executor.submit(_process_port_batch, batch, site_lookup_keys, current_hour)
                for batch in batches
            ]
            
            for future in as_completed(futures):
                circuits, util_records, wan_count, wan_down, wan_disabled = future.result()
                all_circuits.extend(circuits)
                all_utilization_records.extend(util_records)
                total_wan_count += wan_count
                total_wan_down += wan_down
                total_wan_disabled += wan_disabled
        
        # Convert dicts to dataclass instances
        circuits = [
            DimCircuit(**circuit_dict)
            for circuit_dict in all_circuits
        ]
        utilization_records = [
            CircuitUtilizationRecord(**util_dict)
            for util_dict in all_utilization_records
        ]
        wan_port_count = total_wan_count
        
    else:
        # Single-threaded for small datasets
        logger.info(f"[...] Processing {total_ports} ports (single-threaded)")
        circuits = []
        utilization_records = []
        wan_port_count = 0
        
        for port in port_stats:
            device_type = port.get("device_type", "")
            port_usage = port.get("port_usage", "")
            port_id = port.get("port_id", "")
            
            is_wan_port = (
                (device_type == "gateway" and port_usage == "wan") or
                port_usage == "wan" or
                port_id.startswith("lte")
            )
            
            if not is_wan_port:
                continue
            
            # Skip disabled or down ports - track counts
            is_disabled = port.get("disabled", False)
            is_up = port.get("up", True)
            if is_disabled:
                total_wan_disabled += 1
                continue
            if not is_up:
                total_wan_down += 1
                continue
            
            wan_port_count += 1
            site_id = port.get("site_id", "")
            device_mac = port.get("mac", "")
            
            site = site_lookup.get(site_id)
            if not site:
                continue
            
            rx_bps = port.get("rx_bps", 0) or 0
            tx_bps = port.get("tx_bps", 0) or 0
            rx_bytes = port.get("rx_bytes", 0) or 0
            tx_bytes = port.get("tx_bytes", 0) or 0
            speed = port.get("speed", 1000) or 1000
            
            circuit_id = f"{device_mac}:{port_id}"
            circuit = DimCircuit(
                circuit_id=circuit_id,
                site_id=site_id,
                device_id=device_mac,
                port_name=port_id,
                bandwidth_mbps=speed,
                provider="Unknown",
                circuit_type="wan",
                role="primary" if "0" in port_id else "secondary"
            )
            circuits.append(circuit)
            
            utilization_pct = calculate_utilization_pct(
                rx_bps=rx_bps,
                tx_bps=tx_bps,
                speed_mbps=speed
            )
            
            util_record = CircuitUtilizationRecord(
                site_id=site_id,
                circuit_id=circuit_id,
                hour_key=current_hour,
                utilization_pct=round(utilization_pct, 2),
                rx_bytes=rx_bytes,
                tx_bytes=tx_bytes,
                bandwidth_mbps=speed
            )
            utilization_records.append(util_record)
    
    logger.info(f"[OK] Found {wan_port_count} WAN ports up")
    if total_wan_down > 0 or total_wan_disabled > 0:
        logger.info(f"[INFO] WAN ports down: {total_wan_down}, disabled: {total_wan_disabled}")
    
    # Calculate and log total bandwidth
    total_bw_mbps = sum(r.bandwidth_mbps for r in utilization_records)
    logger.info(f"[OK] Created {len(utilization_records)} utilization records, total BW: {total_bw_mbps/1000:.1f} Gbps")
    
    return circuits, utilization_records, total_wan_down, total_wan_disabled


def check_redis_persistence(cache, logger) -> None:
    """
    Check Redis persistence configuration and warn if data is at risk.
    
    Args:
        cache: Redis cache instance
        logger: Logger instance
    """
    try:
        persistence = cache.get_persistence_config()
        
        if persistence.get("error"):
            logger.warning(f"[WARN] Could not check Redis persistence: {persistence['error']}")
            return
        
        is_persisted = persistence.get("data_is_persisted", False)
        aof_enabled = persistence.get("aof_enabled", False)
        rdb_enabled = persistence.get("rdb_enabled", False)
        
        if is_persisted:
            if aof_enabled:
                logger.info("[OK] Redis persistence: AOF enabled (data is safe)")
            elif rdb_enabled:
                last_save = persistence.get("last_save_ago_seconds")
                if last_save:
                    logger.info(f"[OK] Redis persistence: RDB snapshots (last save: {last_save:.0f}s ago)")
                else:
                    logger.info("[OK] Redis persistence: RDB snapshots enabled")
        else:
            logger.warning("=" * 70)
            logger.warning("[WARN] REDIS PERSISTENCE NOT CONFIGURED!")
            logger.warning("[WARN] Historical data will be LOST on Redis restart!")
            logger.warning("[WARN] To fix: docker-compose up -d  (uses redis.conf with AOF)")
            logger.warning("[WARN] Or run: redis-server --appendonly yes")
            logger.warning("=" * 70)
            
    except Exception as error:
        logger.debug(f"Could not check Redis persistence: {error}")


def quick_load_from_cache(config: Config) -> tuple:
    """
    Quickly load any available cached data without API calls.
    
    This function is used to display cached data IMMEDIATELY while
    background refresh runs. No freshness check - just load whatever
    is available in Redis.
    
    Args:
        config: Application configuration
        
    Returns:
        Tuple of (DashboardDataProvider or None, cache or None)
        Returns (None, None) if no cached data available
    """
    logger = logging.getLogger(__name__)
    
    if not config.redis.enabled:
        return None, None
    
    try:
        from src.cache.redis_cache import get_cache
        cache = get_cache(config.redis.url)
        
        if not cache.is_connected():
            logger.warning("[WARN] Redis not connected")
            return None, None
        
        # Load cached sites (required)
        raw_sites = cache.get_sites()
        if not raw_sites:
            logger.info("[INFO] No sites in cache - starting fresh")
            return None, cache
        
        # Load site groups for region names
        sitegroup_map = cache.get_site_groups() or {}
        
        # Convert to dimension models
        sites = []
        for raw_site in raw_sites:
            sitegroup_ids = raw_site.get("sitegroup_ids", [])
            if sitegroup_ids and sitegroup_ids[0] in sitegroup_map:
                region_name = sitegroup_map[sitegroup_ids[0]]
            else:
                region_name = "Unassigned"
            
            site = DimSite(
                site_id=raw_site.get("id", ""),
                site_name=raw_site.get("name", "Unknown"),
                region=region_name,
                timezone=raw_site.get("timezone", "UTC"),
                address=raw_site.get("address", "")
            )
            sites.append(site)
        
        site_lookup = {s.site_id: s for s in sites}
        all_site_ids = list(site_lookup.keys())
        
        # Load all cached port stats (no freshness check)
        port_stats = cache.get_all_site_port_stats(all_site_ids)
        
        if not port_stats:
            # Try global port_stats cache as fallback
            port_stats = cache.get_port_stats() or []
        
        if not port_stats:
            logger.info("[INFO] No port stats in cache - starting fresh")
            return None, cache
        
        logger.info(f"[OK] Quick cache load: {len(port_stats)} port stats from {len(raw_sites)} sites")
        
        # Process into utilization records
        circuits, utilization_records, wan_down, wan_disabled = process_port_stats_to_utilization(
            port_stats, site_lookup, sitegroup_map
        )
        
        if not utilization_records:
            logger.info("[INFO] No WAN ports found in cached data")
            return None, cache
        
        # Create data provider with cached data and Redis cache reference
        provider = DashboardDataProvider(sites=sites, circuits=circuits)
        provider.redis_cache = cache  # Enable historical trends storage/retrieval
        provider.wan_down_count = wan_down
        provider.wan_disabled_count = wan_disabled
        provider.update_utilization(utilization_records)
        
        # Store snapshot for trends history
        provider.store_snapshot_for_trends()
        
        # Load cached SLE data (if available)
        sle_data = cache.get_sle_snapshot()
        if sle_data:
            provider.update_sle_data(sle_data)
            logger.info(f"[OK] Loaded cached SLE data for {sle_data.get('total', 0)} sites")
        
        # Load cached gateway inventory for disconnected site detection
        gateway_inventory = cache.get_gateway_inventory()
        if gateway_inventory:
            provider.update_gateway_inventory(gateway_inventory)
            logger.info(
                f"[OK] Loaded cached gateway inventory: "
                f"{provider.gateways_connected} online, {provider.gateways_disconnected} offline"
            )
        
        # Load cached alarms (if available)
        alarms_data = cache.get_alarms()
        if alarms_data:
            provider.update_alarms(alarms_data)
            logger.info(f"[OK] Loaded cached alarms: {alarms_data.get('total', 0)} alarms")
        
        cache_age = cache.get_cache_age()
        age_str = f"{cache_age:.0f}s" if cache_age else "unknown"
        logger.info(
            f"[OK] Cached data ready: {len(sites)} sites, "
            f"{len(utilization_records)} records (age: {age_str})"
        )
        logger.info("[OK] Dashboard will display cached data immediately")
        
        return provider, cache
        
    except Exception as error:
        logger.warning(f"[WARN] Cache load failed: {error}")
        return None, None


def load_live_data(config: Config) -> tuple:
    """
    Load live data from Mist API including real utilization metrics.
    
    Uses Redis caching with incremental refresh:
    - Sites with cache older than 1 hour get fresh data from API
    - Sites with fresh cache use cached data
    - Reduces API load and speeds up dashboard startup
    
    Args:
        config: Application configuration
        
    Returns:
        Tuple of (DashboardDataProvider, list of site_ids)
        
    Raises:
        ConnectionError: If API connection fails
        ValueError: If no real data can be loaded
    """
    logger = logging.getLogger(__name__)
    
    # Initialize Redis cache (if available)
    cache = None
    if config.redis.enabled:
        try:
            from src.cache.redis_cache import get_cache
            cache = get_cache(config.redis.url)
            if cache.is_connected():
                logger.info(f"[OK] Redis cache connected")
                
                # Check persistence configuration and warn if data at risk
                check_redis_persistence(cache, logger)
                
                # Check if global cache metadata is fresh (for sites/sitegroups)
                # Individual site port stats are checked separately with 1-hour threshold
                if cache.is_cache_fresh(max_age_seconds=config.redis.stale_threshold):
                    cache_age = cache.get_cache_age()
                    logger.info(f"[OK] Using cached data (age: {cache_age:.0f}s)")
                    return load_from_cache(cache, config)
                else:
                    cache_age = cache.get_cache_age()
                    if cache_age:
                        logger.info(f"[INFO] Cache metadata is stale (age: {cache_age:.0f}s)")
                    else:
                        logger.info("[INFO] No cached data found")
                    # Continue to incremental refresh below
            else:
                logger.warning("[WARN] Redis not connected, loading from API")
                cache = None
        except ImportError:
            logger.warning("[WARN] Redis package not installed, caching disabled")
            cache = None
        except Exception as error:
            logger.warning(f"[WARN] Redis error: {error}, caching disabled")
            cache = None
    else:
        logger.info("[INFO] Redis caching disabled by configuration")
    
    # Import API client
    from src.api.mist_client import MistAPIClient
    
    if config.mist is None:
        raise ValueError("Mist configuration is required")
    
    logger.info("[...] Connecting to Mist API")
    client = MistAPIClient(config.mist, config.operational)
    
    # Test connection
    if not client.test_connection():
        raise ConnectionError("Failed to connect to Mist API")
    
    # Load site groups first for human-readable region names
    logger.info("[...] Loading site groups for region names")
    sitegroup_map = client.get_site_groups()
    logger.info(f"[OK] Loaded {len(sitegroup_map)} site groups")
    
    # Cache site groups
    if cache:
        cache.set_site_groups(sitegroup_map)
    
    # Load sites
    logger.info("[...] Loading sites from Mist API")
    raw_sites = client.get_sites()
    logger.info(f"[OK] Loaded {len(raw_sites)} sites")
    
    # Cache sites
    if cache:
        cache.set_sites(raw_sites)
    
    # Build site_id to site mapping for lookups
    site_id_to_raw = {site.get("id"): site for site in raw_sites}
    
    # Convert to dimension models with human-readable region names
    sites = []
    for raw_site in raw_sites:
        # Get first sitegroup_id and map to human-readable name
        sitegroup_ids = raw_site.get("sitegroup_ids", [])
        if sitegroup_ids and sitegroup_ids[0] in sitegroup_map:
            region_name = sitegroup_map[sitegroup_ids[0]]
        else:
            region_name = "Unassigned"
        
        site = DimSite(
            site_id=raw_site.get("id", ""),
            site_name=raw_site.get("name", "Unknown"),
            region=region_name,
            timezone=raw_site.get("timezone", "UTC"),
            address=raw_site.get("address", "")
        )
        sites.append(site)
    
    # Build site lookup
    site_lookup = {s.site_id: s for s in sites}
    all_site_ids = list(site_lookup.keys())
    
    # =========== INCREMENTAL CACHE STRATEGY ===========
    # Check which sites have stale data (older than 1 hour)
    # Fresh sites use cached data, stale sites get fresh API data
    
    port_stats = []
    stale_site_ids = []
    
    if cache:
        # Check per-site cache freshness (1 hour = 3600 seconds)
        max_site_age = 3600  # 1 hour threshold for site-level data
        
        # Get detailed cache status using pipelined method (5-10x faster)
        # Note: This method may not exist on NullCache, so check first
        if hasattr(cache, 'get_stale_site_ids_pipelined'):
            stale_site_ids, fresh_count, missing_count, stale_count = cache.get_stale_site_ids_pipelined(
                all_site_ids, max_age_seconds=max_site_age
            )
            logger.info(
                f"[INFO] Site cache status (pipelined): {fresh_count} fresh, "
                f"{stale_count} stale, {missing_count} missing (max age: {max_site_age}s)"
            )
        elif hasattr(cache, 'get_sites_sorted_by_cache_age'):
            # Fallback to non-pipelined version
            site_ages = cache.get_sites_sorted_by_cache_age(all_site_ids)
            missing_count = sum(1 for _, age in site_ages if age == float('inf'))
            stale_count = sum(1 for _, age in site_ages if age >= max_site_age and age != float('inf'))
            fresh_count = len(all_site_ids) - missing_count - stale_count
            stale_site_ids = cache.get_stale_site_ids(all_site_ids, max_age_seconds=max_site_age)
            
            logger.info(
                f"[INFO] Site cache status: {fresh_count} fresh, "
                f"{stale_count} stale, {missing_count} missing (max age: {max_site_age}s)"
            )
        else:
            fresh_count = 0
            missing_count = len(all_site_ids)
            stale_count = 0
            stale_site_ids = all_site_ids
        
        if stale_site_ids:
            logger.info(
                f"[INFO] Site cache: {fresh_count} fresh, "
                f"{len(stale_site_ids)} need refresh (>{max_site_age}s old)"
            )
        else:
            logger.info(f"[OK] All {len(all_site_ids)} sites have fresh cache (<{max_site_age}s)")
        
        # Load fresh data from per-site cache
        if fresh_count > 0:
            fresh_site_ids = [sid for sid in all_site_ids if sid not in stale_site_ids]
            cached_port_stats = cache.get_all_site_port_stats(fresh_site_ids)
            port_stats.extend(cached_port_stats)
            logger.info(f"[OK] Loaded {len(cached_port_stats)} port stats from cache ({fresh_count} sites)")
    else:
        # No cache - all sites are stale
        stale_site_ids = all_site_ids
    
    # Fetch fresh data from API for stale sites (or all if no cache)
    if stale_site_ids or not cache:
        logger.info("[...] Loading WAN port statistics from API (incremental save enabled)")
        
        # Setup incremental save callback if cache is available
        fetch_session_id = None
        if cache:
            # Check for incomplete fetch session we can resume from
            incomplete = cache.get_incomplete_fetch_session()
            if incomplete:
                logger.info(
                    f"[INFO] Resuming from previous fetch: "
                    f"{incomplete.get('batches_completed', 0)} batches already saved"
                )
                # Use cached data from incomplete session as base
                cached_sites = incomplete.get("sites_saved", [])
                if cached_sites:
                    partial_stats = cache.get_all_site_port_stats(cached_sites)
                    port_stats.extend(partial_stats)
                    logger.info(f"[OK] Recovered {len(partial_stats)} records from partial fetch")
            
            # Start new fetch session for progress tracking
            fetch_session_id = cache.start_fetch_session()
            
            def on_batch_save(batch_records, batch_number, next_cursor):
                """Save each batch immediately as it arrives from API."""
                cache.save_batch_incrementally(
                    port_stats=batch_records,
                    session_id=fetch_session_id,
                    batch_number=batch_number,
                    cursor=next_cursor
                )
            
            api_port_stats = client.get_org_gateway_port_stats(on_batch=on_batch_save)
            
            # Mark fetch session as complete
            cache.complete_fetch_session(fetch_session_id, status="completed")
        else:
            # No cache - just fetch without incremental saves
            api_port_stats = client.get_org_gateway_port_stats()
        
        logger.info(f"[OK] Retrieved {len(api_port_stats)} port stats from API")
        
        # Filter API results to only stale sites (if incremental refresh)
        if cache and stale_site_ids:
            stale_set = set(stale_site_ids)
            fresh_api_stats = [p for p in api_port_stats if p.get("site_id") in stale_set]
            logger.info(f"[OK] Filtered to {len(fresh_api_stats)} port stats for {len(stale_site_ids)} stale sites")
            port_stats.extend(fresh_api_stats)
            
            # Note: Data already saved incrementally via on_batch_save callback
        else:
            # No cache or full refresh - use all API data
            port_stats = api_port_stats
            
            # Cache global port stats for backward compatibility
            if cache:
                cache.set_port_stats(api_port_stats)
                logger.info(f"[OK] Cached {len(api_port_stats)} port stats")
    
    logger.info(f"[OK] Total port stats: {len(port_stats)} records")
    
    # Use shared parallel processing function
    circuits, utilization_records, wan_down, wan_disabled = process_port_stats_to_utilization(
        port_stats, site_lookup, sitegroup_map
    )
    
    # Validate we have real data
    if not utilization_records:
        raise ValueError(
            "No WAN port statistics available from API. "
            "Check that your organization has WAN edge devices with port_usage='wan'."
        )
    
    # Create data provider with Redis cache reference for trends
    provider = DashboardDataProvider(sites=sites, circuits=circuits)
    provider.redis_cache = cache  # Enable historical trends storage/retrieval
    provider.wan_down_count = wan_down
    provider.wan_disabled_count = wan_disabled
    
    # Note: Gateway inventory is loaded at startup (quick API call)
    # No need to reload here - it's already in _data_provider
    
    # Load the real utilization data
    provider.update_utilization(utilization_records)
    
    # Store snapshot for trends history
    provider.store_snapshot_for_trends()
    
    # Mark cache as updated after successful data load
    if cache:
        cache.set_last_update()
        logger.info("[OK] Cache timestamp updated")
        
        # Force Redis to persist data to disk immediately after initial load
        try:
            cache.force_save()
            logger.info("[OK] Cache persisted to disk")
        except Exception as save_error:
            logger.debug(f"Redis save notification: {save_error}")
    
    logger.info(f"[OK] Live data loaded: {len(sites)} sites, {len(utilization_records)} utilization records")
    
    # Store references for background refresh
    global _api_client, _cache
    _api_client = client
    _cache = cache
    
    return provider, all_site_ids


def load_data_async(data_provider: DashboardDataProvider, config: Config):
    """
    Load data from Mist API in a background thread.
    
    Updates the shared data_provider with data as it arrives.
    Dashboard continues running and will display data when available.
    
    Args:
        data_provider: Shared data provider to update
        config: Application configuration
    """
    logger = logging.getLogger(__name__)
    global _api_client, _cache, _background_worker
    
    try:
        logger.info("[...] Background data load starting")
        
        # Mark as loading
        if hasattr(data_provider, 'refresh_activity'):
            data_provider.refresh_activity['status'] = 'loading'
        
        # Load the data (this is the slow part)
        provider, all_site_ids = load_live_data(config)
        
        # Transfer data to the shared provider (including redis_cache reference)
        data_provider.sites = provider.sites
        data_provider.circuits = provider.circuits
        data_provider.site_lookup = provider.site_lookup
        data_provider.region_lookup = provider.region_lookup
        data_provider.circuit_role_lookup = provider.circuit_role_lookup
        data_provider.ranking_views = provider.ranking_views
        data_provider.current_state_views = provider.current_state_views
        data_provider.utilization_records = provider.utilization_records
        data_provider.redis_cache = provider.redis_cache  # Transfer cache reference for trends
        data_provider.data_load_complete = True
        
        logger.info(f"[OK] Background load complete: {len(data_provider.utilization_records)} records")
        
        # Start background refresh if cache is enabled
        if _cache is not None and _api_client is not None:
            from src.cache.background_refresh import BackgroundRefreshWorker, SLEBackgroundWorker, VPNPeerBackgroundWorker
            
            def on_refresh_complete(fresh_stats):
                """Callback when background refresh completes a cycle."""
                # Update refresh activity info
                if hasattr(data_provider, 'refresh_activity'):
                    sites_refreshed = list(set(p.get('site_id', '') for p in fresh_stats))
                    interfaces_refreshed = list(set(p.get('port_id', '') for p in fresh_stats[:20]))
                    data_provider.refresh_activity = {
                        "active": True,
                        "status": "running",
                        "current_sites": sites_refreshed[:10],
                        "current_interfaces": interfaces_refreshed[:10],
                        "last_refresh_time": datetime.now(timezone.utc).isoformat()
                    }
                
                # Store trends snapshot after each refresh cycle
                if hasattr(data_provider, 'store_snapshot_for_trends'):
                    data_provider.store_snapshot_for_trends()
                
                logger.info(f"[OK] Refresh callback: updated {len(fresh_stats)} port stats")
            
            _background_worker = BackgroundRefreshWorker(
                cache=_cache,
                api_client=_api_client,
                site_ids=all_site_ids,
                min_delay_between_fetches=5,  # Minimum 5 seconds between API calls
                max_age_seconds=3600,
                on_data_updated=on_refresh_complete
            )
            _background_worker.start()
            
            # Expose worker to data provider for status queries
            data_provider.background_worker = _background_worker
            logger.info("[OK] Background refresh enabled (continuous mode)")
            
            # Start SLE background worker (collects site-level SLE details)
            global _sle_background_worker
            _sle_background_worker = SLEBackgroundWorker(
                cache=_cache,
                api_client=_api_client,
                data_provider=data_provider,
                min_delay_between_fetches=2,  # 2 seconds between site API calls
                max_age_seconds=3600  # Refresh cache older than 1 hour
            )
            _sle_background_worker.start()
            data_provider.sle_background_worker = _sle_background_worker
            logger.info("[OK] SLE background worker started (site-level collection)")
            
            # Start VPN peer background worker (collects VPN peer path stats)
            global _vpn_peer_background_worker
            _vpn_peer_background_worker = VPNPeerBackgroundWorker(
                cache=_cache,
                api_client=_api_client,
                min_delay_between_fetches=5,  # 5 seconds between API calls
                refresh_interval_seconds=300  # Refresh every 5 minutes
            )
            _vpn_peer_background_worker.start()
            data_provider.vpn_peer_background_worker = _vpn_peer_background_worker
            logger.info("[OK] VPN peer background worker started (peer path collection)")
            
            # Start async precomputers (TaskGroup I/O + ProcessPoolExecutor CPU)
            # These run in a dedicated asyncio event loop in a background thread
            start_async_precomputers(_cache, data_provider)
        
    except Exception as error:
        logger.error(f"[ERROR] Background data load failed: {error}", exc_info=True)


def main():
    """Launch the WAN Performance dashboard."""
    parser = argparse.ArgumentParser(
        description="MistWANPerformance - NOC Dashboard"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("DASH_HOST", "127.0.0.1"),
        help="Host address to bind (default: 127.0.0.1, or DASH_HOST env)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DASH_PORT", "8050")),
        help="Port number (default: 8050, or DASH_PORT env)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)
    
    # Define graceful shutdown handler
    def graceful_shutdown(signum, frame):
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        logger.info(f"[SHUTDOWN] Received signal {sig_name}, initiating graceful shutdown...")
        _shutdown_event.set()
        
        # Stop async precomputers (includes process pool shutdown)
        logger.info("[SHUTDOWN] Stopping async precomputers...")
        stop_async_precomputers()
        
        # Stop background workers
        if _background_worker:
            logger.info("[SHUTDOWN] Stopping port stats background worker...")
            _background_worker.stop()
        if _sle_background_worker:
            logger.info("[SHUTDOWN] Stopping SLE background worker...")
            _sle_background_worker.stop()
        if _vpn_peer_background_worker:
            logger.info("[SHUTDOWN] Stopping VPN peer background worker...")
            _vpn_peer_background_worker.stop()
        
        logger.info("[SHUTDOWN] Background workers stopped, exiting...")
        sys.exit(0)
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    
    logger.info("=" * 60)
    logger.info("MistWANPerformance - NOC Dashboard")
    logger.info("=" * 60)
    
    try:
        # Load configuration
        config = Config()
        
        # STEP 1: Try to load cached data immediately for instant display
        global _data_provider, _cache
        cached_provider, cache_instance = quick_load_from_cache(config)
        
        if cached_provider:
            # Use cached data immediately
            _data_provider = cached_provider
            _cache = cache_instance
            logger.info("[OK] Dashboard will display cached data immediately")
        else:
            # No cache available - create empty provider
            _data_provider = DashboardDataProvider(sites=[], circuits=[])
            _cache = cache_instance  # May still be valid for saving new data
            logger.info("[INFO] No cached data - dashboard will load fresh data")
        
        # STEP 1b: Load or fetch gateway inventory (with Redis caching)
        quick_client = None
        try:
            from src.api.mist_client import MistAPIClient
            
            # Check if cached gateway data is fresh (< 5 minutes old)
            if _cache and _cache.is_gateway_cache_fresh(max_age_seconds=300):
                cached_inventory = _cache.get_gateway_inventory()
                if cached_inventory:
                    _data_provider.gateways_total = cached_inventory.get("total", 0)
                    _data_provider.gateways_connected = cached_inventory.get("connected", 0)
                    _data_provider.gateways_disconnected = cached_inventory.get("disconnected", 0)
                    _data_provider.disconnected_site_ids = _cache.get_disconnected_site_ids()
                    logger.info(
                        f"[OK] Gateway health from cache: {_data_provider.gateways_connected} online, "
                        f"{_data_provider.gateways_disconnected} offline"
                    )
            else:
                # Fetch fresh gateway inventory from API
                if config.mist is not None:
                    logger.info("[...] Fetching gateway inventory (quick API call)")
                    quick_client = MistAPIClient(config.mist, config.operational)
                    gateway_inventory = quick_client.get_gateway_inventory()
                    _data_provider.gateways_total = gateway_inventory.get("total", 0)
                    _data_provider.gateways_connected = gateway_inventory.get("connected", 0)
                    _data_provider.gateways_disconnected = gateway_inventory.get("disconnected", 0)
                    
                    # Build set of site IDs with disconnected gateways
                    disconnected_sites = set()
                    for gw in gateway_inventory.get("gateways", []):
                        if not gw.get("connected", False):
                            site_id = gw.get("site_id")
                            if site_id:
                                disconnected_sites.add(site_id)
                    _data_provider.disconnected_site_ids = disconnected_sites
                    
                    # Save to Redis cache
                    if _cache:
                        _cache.save_gateway_inventory(gateway_inventory)
                    
                    logger.info(
                        f"[OK] Gateway health: {_data_provider.gateways_connected} online, "
                        f"{_data_provider.gateways_disconnected} offline"
                    )
        except Exception as gateway_error:
            logger.warning(f"[WARN] Could not fetch gateway inventory: {gateway_error}")
        
        # STEP 1c: Quick fetch SLE metrics and alarms (single API call each)
        try:
            if config.mist is not None:
                if quick_client is None:
                    quick_client = MistAPIClient(config.mist, config.operational)
                logger.info("[...] Fetching SLE metrics and alarms (quick API calls)")
                
                # Get WAN SLE data for all sites (sle="wan" returns gateway-health, wan-link-health, etc.)
                sle_data = quick_client.get_org_sites_sle(sle="wan")
                if sle_data:
                    _data_provider.update_sle_data(sle_data)
                    # Persist SLE snapshot to Redis (7-day TTL)
                    if _cache:
                        _cache.save_sle_snapshot(sle_data)
                    logger.info(f"[OK] SLE data loaded: {sle_data.get('total', 0)} sites")
                
                # Get worst sites by gateway health
                worst_gateway = quick_client.get_org_worst_sites_by_sle(sle="gateway-health")
                worst_wan = quick_client.get_org_worst_sites_by_sle(sle="wan-link-health")
                if worst_gateway or worst_wan:
                    _data_provider.update_worst_sites(
                        gateway_health=worst_gateway,
                        wan_link=worst_wan
                    )
                    # Persist worst sites to Redis (1-hour TTL)
                    if _cache:
                        if worst_gateway:
                            _cache.save_worst_sites_sle("gateway-health", worst_gateway)
                        if worst_wan:
                            _cache.save_worst_sites_sle("wan-link-health", worst_wan)
                
                # Get recent alarms (last 24 hours)
                alarms_data = quick_client.search_org_alarms(duration="1d", limit=1000)
                if alarms_data:
                    _data_provider.update_alarms(alarms_data)
                    # Persist alarms to Redis (7-day TTL)
                    if _cache:
                        _cache.save_alarms(alarms_data)
                    logger.info(f"[OK] Alarms loaded: {alarms_data.get('total', 0)} alarms")
                    
        except Exception as sle_error:
            logger.warning(f"[WARN] Could not fetch SLE/alarms data: {sle_error}")
        except Exception as gateway_error:
            logger.warning(f"[WARN] Could not fetch gateway inventory: {gateway_error}")
        
        # STEP 2: Start background thread to refresh data (stale or missing)
        logger.info("[INFO] Starting background data refresh...")
        global _data_load_thread
        _data_load_thread = threading.Thread(
            target=load_data_async,
            args=(_data_provider, config),
            daemon=True,
            name="DataLoadThread"
        )
        _data_load_thread.start()
        
        # STEP 2b: Start SLE background worker immediately (doesn't depend on full load)
        try:
            if _cache is not None and quick_client is not None:
                from src.cache.background_refresh import SLEBackgroundWorker, VPNPeerBackgroundWorker
                
                global _sle_background_worker
                _sle_background_worker = SLEBackgroundWorker(
                    cache=_cache,
                    api_client=quick_client,
                    data_provider=_data_provider,
                    min_delay_between_fetches=2,  # 2 seconds between site API calls
                    max_age_seconds=3600  # Refresh cache older than 1 hour
                )
                _sle_background_worker.start()
                _data_provider.sle_background_worker = _sle_background_worker
                logger.info("[OK] SLE background worker started (site-level collection)")
                
                # Start VPN peer background worker
                global _vpn_peer_background_worker
                _vpn_peer_background_worker = VPNPeerBackgroundWorker(
                    cache=_cache,
                    api_client=quick_client,
                    min_delay_between_fetches=5,  # 5 seconds between API calls
                    refresh_interval_seconds=300  # Refresh every 5 minutes
                )
                _vpn_peer_background_worker.start()
                _data_provider.vpn_peer_background_worker = _vpn_peer_background_worker
                logger.info("[OK] VPN peer background worker started (peer path collection)")
                
                # Start async precomputers (TaskGroup I/O + ProcessPoolExecutor CPU)
                # These run in a dedicated asyncio event loop in a background thread
                start_async_precomputers(_cache, _data_provider)
        except Exception as sle_worker_error:
            logger.warning(f"[WARN] Could not start SLE background worker: {sle_worker_error}")
        
        # STEP 3: Start dashboard immediately (shows cached data or loading state)
        dashboard = WANPerformanceDashboard(data_provider=_data_provider)
        logger.info(f"[OK] Dashboard starting at http://{args.host}:{args.port}")
        dashboard.run(host=args.host, port=args.port, debug=args.debug)
        
    except KeyboardInterrupt:
        logger.info("[INFO] Dashboard stopped by user")
        stop_async_precomputers()
        if _background_worker:
            _background_worker.stop()
        if _sle_background_worker:
            _sle_background_worker.stop()
        if _vpn_peer_background_worker:
            _vpn_peer_background_worker.stop()
        return 0
    except ConnectionError as error:
        logger.error(f"[ERROR] API connection failed: {error}")
        stop_async_precomputers()
        if _background_worker:
            _background_worker.stop()
        if _sle_background_worker:
            _sle_background_worker.stop()
        if _vpn_peer_background_worker:
            _vpn_peer_background_worker.stop()
        return 1
    except Exception as error:
        logger.error(f"[ERROR] Dashboard failed: {error}", exc_info=True)
        stop_async_precomputers()
        if _background_worker:
            _background_worker.stop()
        if _sle_background_worker:
            _sle_background_worker.stop()
        if _vpn_peer_background_worker:
            _vpn_peer_background_worker.stop()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
