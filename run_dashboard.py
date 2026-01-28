"""
MistWANPerformance - Dashboard Launcher

Run this script to start the NOC dashboard web interface.

Features:
- Live data from Mist API with Redis caching
- Background refresh: Continuously updates stale data (oldest first)
- No batch limits: Fetches ALL available data

Usage:
    python run_dashboard.py
    python run_dashboard.py --port 8080
    python run_dashboard.py --debug
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from src.utils.logging_config import setup_logging
from src.utils.config import Config
from src.dashboard.app import WANPerformanceDashboard
from src.dashboard.data_provider import DashboardDataProvider
from src.models.dimensions import DimSite, DimCircuit
from src.models.facts import CircuitUtilizationRecord

# Global references for background refresh
_background_worker = None
_api_client = None
_cache = None


def calculate_utilization_pct(
    rx_bytes: int,
    tx_bytes: int,
    speed_mbps: int,
    interval_seconds: int = 300
) -> float:
    """
    Calculate utilization percentage from bytes and port speed.
    
    Args:
        rx_bytes: Received bytes in the interval
        tx_bytes: Transmitted bytes in the interval
        speed_mbps: Port speed in Mbps
        interval_seconds: Measurement interval (default 5 minutes)
    
    Returns:
        Utilization percentage (0.0 - 100.0)
    """
    if speed_mbps <= 0:
        return 0.0
    
    # Use max of rx/tx for utilization (asymmetric traffic)
    max_bytes = max(rx_bytes, tx_bytes)
    
    # Convert to bits per second
    max_bps = (max_bytes * 8) / interval_seconds if interval_seconds > 0 else 0
    
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
    circuits, utilization_records = process_port_stats_to_utilization(
        port_stats, site_lookup, sitegroup_map
    )
    
    if not utilization_records:
        raise ValueError("No utilization records could be created from cached data")
    
    # Create data provider
    provider = DashboardDataProvider(sites=sites, circuits=circuits)
    provider.update_utilization(utilization_records)
    
    logger.info(f"[OK] Cached data loaded: {len(sites)} sites, {len(utilization_records)} utilization records")
    
    # Store cache reference for background refresh
    global _cache
    _cache = cache
    
    # Create API client for background refresh (even when using cache)
    global _api_client
    from src.api.mist_client import MistAPIClient
    _api_client = MistAPIClient(config.mist, config.operational)
    
    return provider, all_site_ids

def process_port_stats_to_utilization(
    port_stats: list,
    site_lookup: dict,
    sitegroup_map: dict
) -> tuple:
    """
    Process port statistics into circuits and utilization records.
    
    Args:
        port_stats: List of port statistics from API/cache
        site_lookup: Dictionary mapping site_id to DimSite
        sitegroup_map: Dictionary mapping sitegroup_id to name
    
    Returns:
        Tuple of (circuits list, utilization_records list)
    """
    logger = logging.getLogger(__name__)
    current_hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    
    circuits = []
    utilization_records = []
    wan_port_count = 0
    
    # Analyze port usage distribution for logging
    port_usage_counts = {}
    for port in port_stats[:500]:
        usage = port.get("port_usage", "NONE")
        port_usage_counts[usage] = port_usage_counts.get(usage, 0) + 1
    logger.info(f"[DEBUG] Port usage values in sample: {port_usage_counts}")
    
    # Sample some port IDs to understand naming
    sample_ports = [(p.get("port_id", ""), p.get("port_usage", "")) for p in port_stats[:20]]
    logger.info(f"[DEBUG] Sample port IDs: {sample_ports}")
    
    for port in port_stats:
        # Filter for WAN ports by port_usage OR by port_id naming convention
        port_usage = port.get("port_usage", "")
        port_id = port.get("port_id", "")
        
        is_wan_port = (
            port_usage == "wan" or
            "wan" in port_id.lower() or
            port_id in ("ge-0/0/0", "ge-0/0/1", "ge-0/0/2", "ge-0/0/3", "ge-1/0/0", "ge-1/0/1") or
            port_id.startswith("lte")
        )
        
        if not is_wan_port:
            continue
        
        wan_port_count += 1
        
        site_id = port.get("site_id", "")
        device_mac = port.get("mac", "")
        
        # Get site info
        site = site_lookup.get(site_id)
        if not site:
            continue
        
        # Port statistics
        rx_bytes = port.get("rx_bytes", 0) or 0
        tx_bytes = port.get("tx_bytes", 0) or 0
        speed = port.get("speed", 1000) or 1000
        
        # Create circuit dimension
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
        
        # Calculate utilization percentage
        utilization_pct = calculate_utilization_pct(
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            speed_mbps=speed,
            interval_seconds=300
        )
        
        # Create utilization record
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
    
    logger.info(f"[OK] Found {wan_port_count} WAN ports")
    logger.info(f"[OK] Created {len(utilization_records)} utilization records")
    
    return circuits, utilization_records


def load_live_data(config: Config) -> DashboardDataProvider:
    """
    Load live data from Mist API including real utilization metrics.
    
    Uses Redis caching with incremental refresh:
    - Sites with cache older than 1 hour get fresh data from API
    - Sites with fresh cache use cached data
    - Reduces API load and speeds up dashboard startup
    
    Args:
        config: Application configuration
        
    Returns:
        Configured DashboardDataProvider with live data
        
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
        stale_site_ids = cache.get_stale_site_ids(all_site_ids, max_age_seconds=max_site_age)
        fresh_site_count = len(all_site_ids) - len(stale_site_ids)
        
        if stale_site_ids:
            logger.info(
                f"[INFO] Site cache: {fresh_site_count} fresh, "
                f"{len(stale_site_ids)} need refresh (>{max_site_age}s old)"
            )
        else:
            logger.info(f"[OK] All {len(all_site_ids)} sites have fresh cache (<{max_site_age}s)")
        
        # Load fresh data from per-site cache
        if fresh_site_count > 0:
            fresh_site_ids = [sid for sid in all_site_ids if sid not in stale_site_ids]
            cached_port_stats = cache.get_all_site_port_stats(fresh_site_ids)
            port_stats.extend(cached_port_stats)
            logger.info(f"[OK] Loaded {len(cached_port_stats)} port stats from cache ({fresh_site_count} sites)")
    else:
        # No cache - all sites are stale
        stale_site_ids = all_site_ids
    
    # Fetch fresh data from API for stale sites (or all if no cache)
    if stale_site_ids or not cache:
        logger.info("[...] Loading WAN port statistics from API (all data, no limits)")
        api_port_stats = client.get_org_gateway_port_stats()
        logger.info(f"[OK] Retrieved {len(api_port_stats)} port stats from API")
        
        # Filter API results to only stale sites (if incremental refresh)
        if cache and stale_site_ids:
            stale_set = set(stale_site_ids)
            fresh_api_stats = [p for p in api_port_stats if p.get("site_id") in stale_set]
            logger.info(f"[OK] Filtered to {len(fresh_api_stats)} port stats for {len(stale_site_ids)} stale sites")
            port_stats.extend(fresh_api_stats)
            
            # Cache the fresh data for stale sites
            cache.set_bulk_site_port_stats(fresh_api_stats)
        else:
            # No cache or full refresh - use all API data
            port_stats = api_port_stats
            
            # Cache all port stats (global and per-site)
            if cache:
                cache.set_port_stats(api_port_stats)
                cache.set_bulk_site_port_stats(api_port_stats)
                logger.info(f"[OK] Cached {len(api_port_stats)} port stats")
    
    logger.info(f"[OK] Total port stats: {len(port_stats)} records")
    
    # Debug: Analyze what port_usage values we have
    port_usage_counts = {}
    for port in port_stats[:500]:  # Sample first 500
        usage = port.get("port_usage", "NONE")
        port_id = port.get("port_id", "")
        port_usage_counts[usage] = port_usage_counts.get(usage, 0) + 1
    logger.info(f"[DEBUG] Port usage values in sample: {port_usage_counts}")
    
    # Sample some port IDs to understand naming
    sample_ports = [(p.get("port_id", ""), p.get("port_usage", "")) for p in port_stats[:20]]
    logger.info(f"[DEBUG] Sample port IDs: {sample_ports}")
    
    # Filter to WAN ports only and create utilization records
    circuits = []
    utilization_records = []
    current_hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    
    wan_port_count = 0
    for port in port_stats:
        # Filter for WAN ports by port_usage OR by port_id naming convention
        port_usage = port.get("port_usage", "")
        port_id = port.get("port_id", "")
        
        # Match: port_usage="wan" OR port_id contains "wan" or starts with "ge-0/0/0" or "ge-0/0/1" (typical WAN ports)
        is_wan_port = (
            port_usage == "wan" or
            "wan" in port_id.lower() or
            port_id in ("ge-0/0/0", "ge-0/0/1", "ge-0/0/2", "ge-0/0/3", "ge-1/0/0", "ge-1/0/1") or
            port_id.startswith("lte")
        )
        
        if not is_wan_port:
            continue
        
        wan_port_count += 1
        
        site_id = port.get("site_id", "")
        device_mac = port.get("mac", "")
        port_id = port.get("port_id", "")
        
        # Get site info
        site = site_lookup.get(site_id)
        if not site:
            continue
        
        # Port statistics
        rx_bytes = port.get("rx_bytes", 0) or 0
        tx_bytes = port.get("tx_bytes", 0) or 0
        speed = port.get("speed", 1000) or 1000  # Default 1 Gbps
        is_up = port.get("up", False)
        
        # Create circuit dimension
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
        
        # Calculate utilization percentage
        utilization_pct = calculate_utilization_pct(
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            speed_mbps=speed,
            interval_seconds=300  # Assume 5-minute polling interval
        )
        
        # Create utilization record
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
    
    logger.info(f"[OK] Found {wan_port_count} WAN ports")
    logger.info(f"[OK] Created {len(utilization_records)} utilization records")
    
    # Validate we have real data
    if not utilization_records:
        raise ValueError(
            "No WAN port statistics available from API. "
            "Check that your organization has WAN edge devices with port_usage='wan'."
        )
    
    # Create data provider
    provider = DashboardDataProvider(sites=sites, circuits=circuits)
    
    # Load the real utilization data
    provider.update_utilization(utilization_records)
    
    # Mark cache as updated after successful data load
    if cache:
        cache.set_last_update()
        logger.info("[OK] Cache timestamp updated")
    
    logger.info(f"[OK] Live data loaded: {len(sites)} sites, {len(utilization_records)} utilization records")
    
    # Store references for background refresh
    global _api_client, _cache
    _api_client = client
    _cache = cache
    
    return provider, all_site_ids


def main():
    """Launch the WAN Performance dashboard."""
    parser = argparse.ArgumentParser(
        description="MistWANPerformance - NOC Dashboard"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port number (default: 8050)"
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
    
    logger.info("=" * 60)
    logger.info("MistWANPerformance - NOC Dashboard")
    logger.info("=" * 60)
    
    try:
        # Load live data from Mist API (required - no demo mode)
        logger.info("[INFO] Loading live data from Mist API...")
        config = Config()
        data_provider, all_site_ids = load_live_data(config)
        logger.info("[OK] Live data loaded successfully")
        
        # Verify real data was loaded
        dashboard_data = data_provider.get_dashboard_data()
        logger.info(f"[OK] Dashboard data ready: {dashboard_data['total_sites']} sites with utilization data")
        logger.info(f"[OK] Top congested sites: {[c['site_name'] for c in dashboard_data['top_congested'][:3]]}")
        
        # Start background refresh if cache is enabled
        global _background_worker
        if _cache is not None and _api_client is not None:
            from src.cache.background_refresh import BackgroundRefreshWorker
            
            _background_worker = BackgroundRefreshWorker(
                cache=_cache,
                api_client=_api_client,
                site_ids=all_site_ids,
                refresh_interval_seconds=300,  # Check every 5 minutes
                max_sites_per_cycle=100,       # Refresh up to 100 oldest sites per cycle
                max_age_seconds=3600           # Sites older than 1 hour are stale
            )
            _background_worker.start()
            logger.info("[OK] Background refresh enabled (5 min interval, oldest sites first)")
        else:
            logger.info("[INFO] Background refresh disabled (no cache)")
        
        # Create and run dashboard
        dashboard = WANPerformanceDashboard(data_provider=data_provider)
        dashboard.run(host=args.host, port=args.port, debug=args.debug)
        
    except KeyboardInterrupt:
        logger.info("[INFO] Dashboard stopped by user")
        if _background_worker:
            _background_worker.stop()
        return 0
    except ValueError as error:
        logger.error(f"[ERROR] No real data available: {error}")
        logger.error("[ERROR] Dashboard requires live API data. Check your Mist API configuration.")
        if _background_worker:
            _background_worker.stop()
        return 1
    except ConnectionError as error:
        logger.error(f"[ERROR] API connection failed: {error}")
        if _background_worker:
            _background_worker.stop()
        return 1
    except Exception as error:
        logger.error(f"[ERROR] Dashboard failed: {error}", exc_info=True)
        if _background_worker:
            _background_worker.stop()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
