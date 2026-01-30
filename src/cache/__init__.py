"""
MistWANPerformance - Cache Module

Provides Redis caching for Mist API data to reduce API calls
and improve dashboard startup performance.

Supports both threading (legacy) and asyncio (preferred) modes.
"""

from src.cache.redis_cache import RedisCache
from src.cache.background_refresh import (
    BackgroundRefreshWorker,
    AsyncBackgroundRefreshWorker,
    refresh_stale_sites_parallel,
)

__all__ = [
    "RedisCache",
    "BackgroundRefreshWorker",
    "AsyncBackgroundRefreshWorker",
    "refresh_stale_sites_parallel",
]
