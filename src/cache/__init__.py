"""
MistWANPerformance - Cache Module

Provides Redis caching for Mist API data to reduce API calls
and improve dashboard startup performance.

Supports both threading (legacy) and asyncio (preferred) modes.
Async precomputers use TaskGroup for I/O parallelism and
ProcessPoolExecutor for CPU-bound computation.
"""

from src.cache.redis_cache import RedisCache
from src.cache.background_refresh import (
    BackgroundRefreshWorker,
    AsyncBackgroundRefreshWorker,
    refresh_stale_sites_parallel,
)
from src.cache.dashboard_precompute import DashboardPrecomputer
from src.cache.site_precompute import SiteSlePrecomputer, SiteVpnPrecomputer

# Async precomputers (parallelized with asyncio + ProcessPoolExecutor)
from src.cache.async_precompute import (
    AsyncDashboardPrecomputer,
    AsyncSiteSlePrecomputer,
    AsyncSiteVpnPrecomputer,
    get_process_pool,
    shutdown_process_pool,
)

__all__ = [
    "RedisCache",
    "BackgroundRefreshWorker",
    "AsyncBackgroundRefreshWorker",
    "refresh_stale_sites_parallel",
    # Threading-based precomputers (legacy)
    "DashboardPrecomputer",
    "SiteSlePrecomputer",
    "SiteVpnPrecomputer",
    # Async precomputers (preferred)
    "AsyncDashboardPrecomputer",
    "AsyncSiteSlePrecomputer",
    "AsyncSiteVpnPrecomputer",
    "get_process_pool",
    "shutdown_process_pool",
]

