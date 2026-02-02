"""
WSGI entry point for MistWANPerformance Dashboard.

This module creates the Dash application and exposes its Flask server
for use with production WSGI servers like Gunicorn.

Usage with Gunicorn:
    gunicorn -c gunicorn_config.py wsgi:server
"""

import os
import sys
import logging

# Ensure src is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.dashboard.app import WANPerformanceDashboard
from src.dashboard.data_provider import DashboardDataProvider
from src.models.dimensions import DimSite, DimCircuit
from src.cache.redis_cache import RedisCache
from src.cache.async_precompute import (
    AsyncDashboardPrecomputer,
    AsyncSiteSlePrecomputer, 
    AsyncSiteVpnPrecomputer,
    start_async_precomputers,
)
from src.cache.background_refresh import (
    BackgroundRefreshWorker,
    SLEBackgroundWorker,
    VPNPeerBackgroundWorker,
)
from src.api.mist_client import MistAPIClient

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global instances (shared across workers if preload_app=True)
_dashboard = None
_background_workers = []


def create_app():
    """
    Create and configure the Dash application.
    
    Returns:
        Flask server instance (for WSGI)
    """
    global _dashboard, _background_workers
    
    logger.info("=" * 60)
    logger.info("MistWANPerformance - NOC Dashboard (Gunicorn)")
    logger.info("=" * 60)
    
    # Connect to Redis
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    
    try:
        redis_cache = RedisCache(host=redis_host, port=redis_port)
        logger.info(f"[OK] Connected to Redis at redis://{redis_host}:{redis_port}")
    except Exception as e:
        logger.error(f"[ERROR] Failed to connect to Redis: {e}")
        redis_cache = None
    
    # Load cached data
    sites = []
    circuits = []
    records = []
    
    if redis_cache:
        try:
            # Quick load from cache
            port_stats = redis_cache.get_all_site_port_stats()
            if port_stats:
                logger.info(f"[OK] Loaded {len(port_stats)} port stats from Redis")
                # Process port stats into records (simplified)
        except Exception as e:
            logger.warning(f"[WARN] Cache load failed: {e}")
    
    # Create data provider with empty initial data
    provider = DashboardDataProvider(
        sites=[],
        circuits=[],
        utilization_records=[]
    )
    
    if redis_cache:
        provider.redis_cache = redis_cache
    
    # Create dashboard
    _dashboard = WANPerformanceDashboard(
        app_name="WAN Performance - NOC Dashboard",
        data_provider=provider
    )
    
    # Initialize background workers if we have Redis and API credentials
    api_token = os.getenv("MIST_API_TOKEN")
    if redis_cache and api_token:
        try:
            api_client = MistAPIClient()
            
            # Get site IDs from SLE data (already loaded into provider)
            site_ids = []
            if hasattr(provider, 'sle_data') and provider.sle_data:
                site_ids = [r.get("site_id") for r in provider.sle_data.get("results", []) if r.get("site_id")]
            if not site_ids:
                # Fallback to cache
                site_ids = list(redis_cache.get_all_site_ids()) if hasattr(redis_cache, 'get_all_site_ids') else []
            
            logger.info(f"[INFO] Starting background workers with {len(site_ids)} sites")
            
            # Start background refresh worker (port stats / utilization)
            # This worker fetches ALL org port stats, doesn't need site_ids
            refresh_worker = BackgroundRefreshWorker(
                cache=redis_cache,
                api_client=api_client,
                site_ids=site_ids,
                min_delay_between_fetches=5,
                max_age_seconds=3600
            )
            refresh_worker.start()
            _background_workers.append(refresh_worker)
            provider.background_worker = refresh_worker
            logger.info("[OK] Port stats background worker started")
            
            # Start SLE background worker (site-level SLE details)
            # This worker uses data_provider to get site list and degraded sites
            sle_worker = SLEBackgroundWorker(
                cache=redis_cache,
                api_client=api_client,
                data_provider=provider,
                max_age_seconds=3600
            )
            sle_worker.start()
            _background_workers.append(sle_worker)
            provider.sle_background_worker = sle_worker
            logger.info("[OK] SLE background worker started")
            
            # Start VPN peer background worker
            vpn_worker = VPNPeerBackgroundWorker(
                cache=redis_cache,
                api_client=api_client,
                min_delay_between_fetches=5,
                refresh_interval_seconds=300
            )
            vpn_worker.start()
            _background_workers.append(vpn_worker)
            provider.vpn_background_worker = vpn_worker
            logger.info("[OK] VPN peer background worker started")
            
        except Exception as e:
            logger.error(f"[ERROR] Failed to start background workers: {e}", exc_info=True)
    
    # Return the Flask server for Gunicorn
    return _dashboard.app.server


# Create the application
# This is called when Gunicorn imports this module
server = create_app()


def shutdown():
    """Cleanup function for graceful shutdown."""
    global _background_workers
    
    logger.info("[SHUTDOWN] Stopping background workers...")
    for worker in _background_workers:
        if hasattr(worker, 'stop'):
            worker.stop()
    
    logger.info("[SHUTDOWN] Shutdown complete")
