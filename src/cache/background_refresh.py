"""
MistWANPerformance - Background Cache Refresh

Continuously refreshes stale cache data in the background while
the dashboard is running. Prioritizes oldest data first.

NASA/JPL Pattern: Safety-first with graceful degradation.
Handles 429 rate limits by pausing until top of hour reset.

Supports both threading (legacy) and asyncio (preferred) modes.
Asyncio mode can use either sync API (via executor) or true async API.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Union

from src.api.mist_client import RateLimitError, get_rate_limit_status, is_rate_limited
from src.api.async_mist_client import AsyncMistAPIClient

logger = logging.getLogger(__name__)


# ============================================================================
# Async Background Refresh Worker (Preferred for new code)
# ============================================================================


class AsyncBackgroundRefreshWorker:
    """
    Async background worker that refreshes stale cache data.
    
    Uses asyncio for non-blocking operations with parallel site refresh
    capabilities via TaskGroup. Preferred over threading for new code.
    
    Supports two API modes:
    - Sync API (legacy): Uses run_in_executor to call sync MistAPIClient
    - Async API (preferred): Uses AsyncMistAPIClient for true async HTTP
    
    Strategy:
    1. First pass: Get data for ALL sites (fill gaps)
    2. Subsequent passes: Refresh oldest data first (keep fresh)
    """
    
    def __init__(
        self,
        cache,
        api_client: Union[Any, AsyncMistAPIClient],
        site_ids: List[str],
        min_delay_between_fetches: int = 5,
        max_age_seconds: int = 3600,
        on_data_updated: Optional[Callable] = None,
        parallel_site_limit: int = 5,
        use_async_api: bool = False
    ):
        """
        Initialize the async background refresh worker.
        
        Args:
            cache: Redis cache instance
            api_client: Mist API client instance (sync or async)
            site_ids: List of all site IDs to monitor
            min_delay_between_fetches: Minimum seconds between API calls
            max_age_seconds: Cache age threshold for staleness (default: 1 hour)
            on_data_updated: Optional callback when data is refreshed
            parallel_site_limit: Max concurrent site refreshes (default: 5)
            use_async_api: If True, api_client is AsyncMistAPIClient (default: False)
        """
        self.cache = cache
        self.api_client = api_client
        self.site_ids = site_ids
        self.min_delay = min_delay_between_fetches
        self.max_age_seconds = max_age_seconds
        self.on_data_updated = on_data_updated
        self.parallel_site_limit = parallel_site_limit
        self.use_async_api = use_async_api
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_refresh_time = 0.0
        self._total_sites_refreshed = 0
        self._refresh_cycles = 0
        self._initial_coverage_complete = False
        self._sites_with_data: set = set()
        self._rate_limited = False
    
    async def start(self) -> None:
        """Start the async background refresh worker."""
        if self._running:
            logger.warning("[WARN] Async background refresh already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(
            self._refresh_loop(),
            name="AsyncBackgroundRefreshWorker"
        )
        logger.info(
            f"[OK] Async background refresh started "
            f"({len(self.site_ids)} sites, parallel limit: {self.parallel_site_limit})"
        )
    
    async def stop(self) -> None:
        """Stop the async background refresh worker."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected when stopping
        
        logger.info(
            f"[OK] Async background refresh stopped "
            f"(cycles: {self._refresh_cycles}, total: {self._total_sites_refreshed})"
        )
    
    async def _refresh_loop(self) -> None:
        """Main async refresh loop - runs continuously."""
        logger.info("[...] Async background refresh loop starting")
        
        while self._running:
            try:
                # Check rate limit before API call
                if is_rate_limited():
                    rate_status = get_rate_limit_status()
                    remaining = rate_status.get("seconds_remaining", 60)
                    self._rate_limited = True
                    
                    logger.warning(
                        f"[RATE LIMIT] API rate limited - pausing async refresh. "
                        f"Resume in {int(remaining // 60)}m {int(remaining % 60)}s"
                    )
                    await asyncio.sleep(min(60, int(remaining) + 1))
                    continue
                
                if self._rate_limited:
                    self._rate_limited = False
                    logger.info("[OK] Rate limit cleared - resuming async refresh")
                
                cycle_start = time.time()
                await self._run_refresh_cycle_async()
                cycle_duration = time.time() - cycle_start
                
                # No delay - stay busy, immediately start next cycle
                    
            except asyncio.CancelledError:
                logger.info("[INFO] Async refresh loop cancelled")
                break
                
            except RateLimitError as rate_error:
                self._rate_limited = True
                wait_time = rate_error.seconds_remaining or 3600
                logger.error(
                    f"[RATE LIMIT] Hit 429 during async refresh - pausing "
                    f"{int(wait_time // 60)}m {int(wait_time % 60)}s"
                )
                await asyncio.sleep(int(wait_time) + 5)
                
            except Exception as error:
                logger.error(f"[ERROR] Async refresh error: {error}", exc_info=True)
                # Brief yield to prevent CPU spin on repeated errors
                await asyncio.sleep(0.1)
    
    async def _run_refresh_cycle_async(self) -> None:
        """Execute one async refresh cycle with parallel site processing."""
        self._refresh_cycles += 1
        cycle_start = time.time()
        
        # Get stale site IDs
        stale_ids, fresh_count, missing_count, stale_count = self._get_stale_sites()
        
        # Log coverage status
        self._log_coverage_status(fresh_count, missing_count, stale_count)
        
        # Fetch and cache all port stats (bulk operation)
        await self._fetch_and_cache_port_stats(cycle_start)
    
    def _get_stale_sites(self) -> tuple:
        """Get stale site IDs and cache statistics."""
        if hasattr(self.cache, 'get_stale_site_ids_pipelined'):
            return self.cache.get_stale_site_ids_pipelined(
                self.site_ids, max_age_seconds=self.max_age_seconds
            )
        
        site_ages = self.cache.get_sites_sorted_by_cache_age(self.site_ids)
        missing = sum(1 for _, age in site_ages if age == float('inf'))
        stale = sum(1 for _, age in site_ages if age >= self.max_age_seconds and age != float('inf'))
        fresh = len(self.site_ids) - missing - stale
        stale_ids = [sid for sid, age in site_ages if age >= self.max_age_seconds]
        return stale_ids, fresh, missing, stale
    
    def _log_coverage_status(self, fresh: int, missing: int, stale: int) -> None:
        """Log cache coverage status."""
        if not self._initial_coverage_complete:
            coverage = ((fresh + stale) / len(self.site_ids)) * 100 if self.site_ids else 0
            if missing == 0:
                self._initial_coverage_complete = True
                logger.info(
                    f"[OK] Initial coverage complete! All {len(self.site_ids)} sites cached"
                )
            else:
                logger.info(
                    f"[...] Async cycle {self._refresh_cycles}: {coverage:.1f}% coverage "
                    f"({fresh} fresh, {stale} stale, {missing} missing)"
                )
        elif self._refresh_cycles % 10 == 0:
            logger.info(
                f"[INFO] Async cycle {self._refresh_cycles}: "
                f"{fresh} fresh, {stale} stale, {missing} missing"
            )
    
    async def _fetch_and_cache_port_stats(self, cycle_start: float) -> None:
        """Fetch all port stats and cache them."""
        try:
            # Use true async API if available, otherwise fall back to executor
            if self.use_async_api and isinstance(self.api_client, AsyncMistAPIClient):
                all_port_stats = await self.api_client.get_org_gateway_port_stats_async()
            else:
                # Run blocking API call in thread pool to avoid blocking event loop
                loop = asyncio.get_event_loop()
                all_port_stats = await loop.run_in_executor(
                    None, self.api_client.get_org_gateway_port_stats
                )
            
            if not all_port_stats:
                logger.warning("[WARN] Async API returned no port stats")
                return
            
            # Cache data (may also be blocking - run in executor)
            loop = asyncio.get_event_loop()
            sites_cached = await loop.run_in_executor(
                None, self.cache.set_bulk_site_port_stats, all_port_stats
            )
            self._total_sites_refreshed += sites_cached
            
            # Track sites with data
            sites_in_response = set(
                port.get("site_id") for port in all_port_stats if port.get("site_id")
            )
            self._sites_with_data.update(sites_in_response)
            
            # Force Redis save
            try:
                await loop.run_in_executor(None, self.cache.force_save)
            except Exception as save_error:
                logger.debug(f"Redis save notification: {save_error}")
            
            cycle_duration = time.time() - cycle_start
            api_mode = "async" if self.use_async_api else "sync-executor"
            
            if not self._initial_coverage_complete or self._refresh_cycles <= 3:
                logger.info(
                    f"[OK] Async cycle {self._refresh_cycles} ({api_mode}): "
                    f"Cached {sites_cached} sites, {len(all_port_stats)} ports "
                    f"in {cycle_duration:.1f}s"
                )
            
            # Notify callback
            if self.on_data_updated:
                try:
                    self.on_data_updated(all_port_stats)
                except Exception as callback_error:
                    logger.error(f"[ERROR] Async callback failed: {callback_error}")
        
        except RateLimitError:
            raise
        except Exception as api_error:
            logger.error(f"[ERROR] Async API fetch failed: {api_error}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current async worker status for monitoring."""
        rate_status = get_rate_limit_status()
        return {
            "running": self._running,
            "mode": "async",
            "api_mode": "async-http" if self.use_async_api else "sync-executor",
            "refresh_cycles": self._refresh_cycles,
            "total_sites_refreshed": self._total_sites_refreshed,
            "last_refresh_time": self._last_refresh_time,
            "min_delay_seconds": self.min_delay,
            "max_age_seconds": self.max_age_seconds,
            "monitored_site_count": len(self.site_ids),
            "initial_coverage_complete": self._initial_coverage_complete,
            "sites_with_data_count": len(self._sites_with_data),
            "parallel_site_limit": self.parallel_site_limit,
            "rate_limited": self._rate_limited or rate_status.get("rate_limited", False),
            "rate_limit_status": rate_status
        }
    
    @property
    def is_running(self) -> bool:
        """Check if async worker is currently running."""
        return self._running


async def refresh_stale_sites_parallel(
    cache,
    api_client,
    stale_site_ids: List[str],
    max_concurrent: int = 5
) -> int:
    """
    Refresh multiple stale sites in parallel using asyncio TaskGroup.
    
    Args:
        cache: Redis cache instance
        api_client: Mist API client with per-site fetch capability
        stale_site_ids: List of site IDs needing refresh
        max_concurrent: Maximum concurrent refreshes (default: 5)
    
    Returns:
        Number of sites successfully refreshed
    """
    if not stale_site_ids:
        return 0
    
    refreshed_count = 0
    semaphore = asyncio.Semaphore(max_concurrent)
    loop = asyncio.get_event_loop()
    
    async def refresh_single_site(site_id: str) -> bool:
        """Refresh a single site with semaphore limiting."""
        async with semaphore:
            try:
                # Check rate limit before each call
                if is_rate_limited():
                    logger.debug(f"[SKIP] Rate limited, skipping site {site_id}")
                    return False
                
                # Run blocking API call in executor
                port_stats = await loop.run_in_executor(
                    None, lambda: api_client.get_site_gateway_port_stats(site_id)
                )
                
                if port_stats:
                    await loop.run_in_executor(
                        None, lambda: cache.set_site_port_stats(site_id, port_stats)
                    )
                    return True
                return False
                
            except RateLimitError:
                logger.warning(f"[RATE LIMIT] Hit limit refreshing site {site_id}")
                return False
            except Exception as error:
                logger.error(f"[ERROR] Failed to refresh site {site_id}: {error}")
                return False
    
    # Use TaskGroup for structured concurrency (Python 3.11+)
    try:
        async with asyncio.TaskGroup() as task_group:
            tasks = [
                task_group.create_task(refresh_single_site(site_id))
                for site_id in stale_site_ids
            ]
        
        # Count successful refreshes
        refreshed_count = sum(1 for task in tasks if task.result())
        
    except ExceptionGroup as exception_group:
        # Handle any exceptions from the TaskGroup
        logger.error(f"[ERROR] TaskGroup exceptions: {len(exception_group.exceptions)} errors")
        for error in exception_group.exceptions[:3]:  # Log first 3 errors
            logger.error(f"  - {type(error).__name__}: {error}")
    
    logger.info(
        f"[OK] Parallel refresh complete: {refreshed_count}/{len(stale_site_ids)} sites"
    )
    return refreshed_count


# ============================================================================
# Threading-based Background Refresh Worker (Legacy compatibility)
# ============================================================================


class BackgroundRefreshWorker:
    """
    Background worker that refreshes stale cache data.
    
    Runs in a separate thread, continuously fetching fresh data
    from the API. Strategy:
    1. First pass: Get data for ALL sites (fill gaps)
    2. Subsequent passes: Refresh oldest data first (keep fresh)
    
    No artificial limits - refresh as fast as the API allows.
    """
    
    def __init__(
        self,
        cache,
        api_client,
        site_ids: List[str],
        min_delay_between_fetches: int = 5,
        max_age_seconds: int = 3600,
        on_data_updated: Optional[Callable] = None
    ):
        """
        Initialize the background refresh worker.
        
        Args:
            cache: Redis cache instance
            api_client: Mist API client instance
            site_ids: List of all site IDs to monitor
            min_delay_between_fetches: Minimum seconds between API calls (rate limit protection)
            max_age_seconds: Cache age threshold for staleness (default: 1 hour)
            on_data_updated: Optional callback when data is refreshed
        """
        self.cache = cache
        self.api_client = api_client
        self.site_ids = site_ids
        self.min_delay = min_delay_between_fetches
        self.max_age_seconds = max_age_seconds
        self.on_data_updated = on_data_updated
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_refresh_time = 0
        self._total_sites_refreshed = 0
        self._refresh_cycles = 0
        self._initial_coverage_complete = False
        self._sites_with_data: set = set()
        self._rate_limited = False
        self._rate_limit_resume_time: Optional[float] = None
    
    def start(self) -> None:
        """Start the background refresh worker thread."""
        if self._running:
            logger.warning("[WARN] Background refresh already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._refresh_loop,
            name="BackgroundRefreshWorker",
            daemon=True  # Thread stops when main program exits
        )
        self._thread.start()
        logger.info(
            f"[OK] Background refresh started "
            f"(continuous mode, {len(self.site_ids)} sites, min delay: {self.min_delay}s)"
        )
    
    def stop(self) -> None:
        """Stop the background refresh worker."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info(
            f"[OK] Background refresh stopped "
            f"(cycles: {self._refresh_cycles}, total sites refreshed: {self._total_sites_refreshed})"
        )
    
    def _refresh_loop(self) -> None:
        """Main refresh loop - runs continuously in background thread."""
        logger.info("[...] Background refresh loop starting (continuous mode)")
        
        while self._running:
            try:
                # Check if we're rate limited before attempting any API call
                if is_rate_limited():
                    rate_status = get_rate_limit_status()
                    remaining = rate_status.get("seconds_remaining", 60)
                    self._rate_limited = True
                    
                    # Log once per minute while waiting
                    logger.warning(
                        f"[RATE LIMIT] API rate limited - pausing refresh. "
                        f"Resume in {int(remaining // 60)}m {int(remaining % 60)}s"
                    )
                    # Sleep for 60 seconds then check again
                    self._interruptible_sleep(min(60, int(remaining) + 1))
                    continue
                
                # Clear rate limit flag when we can proceed
                if self._rate_limited:
                    self._rate_limited = False
                    logger.info("[OK] Rate limit cleared - resuming refresh operations")
                
                cycle_start = time.time()
                self._run_refresh_cycle()
                cycle_duration = time.time() - cycle_start
                
                # No delay - stay busy, immediately start next cycle
                    
            except RateLimitError as rate_error:
                # Handle rate limit errors from the API
                self._rate_limited = True
                wait_time = rate_error.seconds_remaining or 3600
                logger.error(
                    f"[RATE LIMIT] Hit 429 during refresh - pausing for "
                    f"{int(wait_time // 60)}m {int(wait_time % 60)}s until top of hour"
                )
                # Sleep until reset time
                self._interruptible_sleep(int(wait_time) + 5)
                    
            except Exception as error:
                logger.error(f"[ERROR] Background refresh error: {error}", exc_info=True)
                # Brief pause on error before retry (0.1s to prevent CPU spin)
                self._interruptible_sleep(0.1)
    
    def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep that can be interrupted by stop()."""
        end_time = time.time() + seconds
        while self._running and time.time() < end_time:
            time.sleep(1)  # Check every second if we should stop
    
    def _run_refresh_cycle(self) -> None:
        """Execute one refresh cycle - fetch ALL data, cache ALL sites."""
        self._refresh_cycles += 1
        cycle_start = time.time()
        
        # Check current cache state
        if hasattr(self.cache, 'get_stale_site_ids_pipelined'):
            stale_ids, fresh_count, missing_count, stale_count = self.cache.get_stale_site_ids_pipelined(
                self.site_ids, max_age_seconds=self.max_age_seconds
            )
        else:
            site_ages = self.cache.get_sites_sorted_by_cache_age(self.site_ids)
            missing_count = sum(1 for _, age in site_ages if age == float('inf'))
            stale_count = sum(1 for _, age in site_ages if age >= self.max_age_seconds and age != float('inf'))
            fresh_count = len(self.site_ids) - missing_count - stale_count
        
        # Track initial coverage (have we hit every site at least once?)
        if not self._initial_coverage_complete:
            coverage_pct = ((fresh_count + stale_count) / len(self.site_ids)) * 100 if self.site_ids else 0
            if missing_count == 0:
                self._initial_coverage_complete = True
                logger.info(
                    f"[OK] Initial coverage complete! All {len(self.site_ids)} sites have data. "
                    f"Now maintaining freshness..."
                )
            else:
                logger.info(
                    f"[...] Cycle {self._refresh_cycles}: Coverage {coverage_pct:.1f}% "
                    f"({fresh_count} fresh, {stale_count} stale, {missing_count} missing)"
                )
        else:
            # After initial coverage, just log refresh status
            if self._refresh_cycles % 10 == 0:  # Log every 10th cycle to avoid spam
                logger.info(
                    f"[INFO] Cycle {self._refresh_cycles}: "
                    f"{fresh_count} fresh, {stale_count} stale, {missing_count} missing"
                )
        
        # Fetch ALL port stats from API (the API returns everything anyway)
        try:
            all_port_stats = self.api_client.get_org_gateway_port_stats()
            
            if not all_port_stats:
                logger.warning("[WARN] API returned no port stats")
                return
            
            # Cache ALL data - no filtering, no limits
            sites_cached = self.cache.set_bulk_site_port_stats(all_port_stats)
            self._total_sites_refreshed += sites_cached
            
            # Track which sites have data
            sites_in_response = set(port.get("site_id") for port in all_port_stats if port.get("site_id"))
            self._sites_with_data.update(sites_in_response)
            
            # Force Redis to save data to disk
            try:
                self.cache.force_save()
            except Exception as save_error:
                logger.debug(f"Redis save notification: {save_error}")
            
            cycle_duration = time.time() - cycle_start
            
            # Log completion (less verbose after initial coverage)
            if not self._initial_coverage_complete or self._refresh_cycles <= 3:
                logger.info(
                    f"[OK] Cycle {self._refresh_cycles}: "
                    f"Cached {sites_cached} sites, {len(all_port_stats)} ports in {cycle_duration:.1f}s"
                )
            
            # Notify callback if provided
            if self.on_data_updated:
                try:
                    self.on_data_updated(all_port_stats)
                except Exception as callback_error:
                    logger.error(f"[ERROR] Data update callback failed: {callback_error}")
        
        except RateLimitError:
            # Re-raise rate limit errors to be handled by the refresh loop
            raise
        except Exception as api_error:
            logger.error(f"[ERROR] API fetch failed in refresh cycle: {api_error}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current worker status for monitoring."""
        rate_status = get_rate_limit_status()
        return {
            "running": self._running,
            "refresh_cycles": self._refresh_cycles,
            "total_sites_refreshed": self._total_sites_refreshed,
            "last_refresh_time": self._last_refresh_time,
            "min_delay_seconds": self.min_delay,
            "max_age_seconds": self.max_age_seconds,
            "monitored_site_count": len(self.site_ids),
            "initial_coverage_complete": self._initial_coverage_complete,
            "sites_with_data_count": len(self._sites_with_data),
            "mode": "continuous",
            "rate_limited": self._rate_limited or rate_status.get("rate_limited", False),
            "rate_limit_status": rate_status
        }
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running


# ============================================================================
# Site-Level SLE Background Collector
# ============================================================================


class SLEBackgroundWorker:
    """
    Background worker for collecting site-level SLE data.
    
    Prioritizes degraded sites first, then collects data for all sites.
    Uses a separate thread to avoid blocking the main dashboard.
    """
    
    def __init__(
        self,
        cache,
        api_client,
        data_provider,
        min_delay_between_fetches: int = 1,
        max_age_seconds: int = 3600,
        on_site_collected: Optional[Callable] = None
    ):
        """
        Initialize the SLE background worker.
        
        Args:
            cache: Redis cache instance
            api_client: Mist API client instance
            data_provider: Dashboard data provider (for degraded sites list)
            min_delay_between_fetches: Minimum seconds between API calls
            max_age_seconds: Cache age threshold for staleness (default: 1 hour)
            on_site_collected: Optional callback when a site is collected
        """
        self.cache = cache
        self.api_client = api_client
        self.data_provider = data_provider
        self.min_delay = min_delay_between_fetches
        self.max_age_seconds = max_age_seconds
        self.on_site_collected = on_site_collected
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._total_sites_collected = 0
        self._degraded_sites_collected = 0
        self._collection_cycles = 0
        self._rate_limited = False
        self._current_site: Optional[str] = None
    
    def start(self) -> None:
        """Start the SLE background worker."""
        if self._running:
            logger.warning("[WARN] SLE background worker already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._collection_loop,
            daemon=True,
            name="SLEBackgroundWorker"
        )
        self._thread.start()
        logger.info("[OK] SLE background worker started")
    
    def stop(self) -> None:
        """Stop the SLE background worker."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info(
            f"[OK] SLE background worker stopped "
            f"(collected {self._total_sites_collected} sites, "
            f"{self._degraded_sites_collected} degraded)"
        )
    
    def _collection_loop(self) -> None:
        """Main collection loop - runs continuously with auto-restart on errors."""
        logger.info("[...] SLE background collection starting")
        
        # Import here to avoid circular imports
        from src.collectors.sle_collector import SLECollector
        
        restart_count = 0
        max_restarts = 100  # Allow many restarts before giving up
        
        while self._running and restart_count < max_restarts:
            try:
                sle_collector = SLECollector(
                    api_client=self.api_client,
                    cache=self.cache
                )
                
                self._run_inner_loop(sle_collector)
                
            except Exception as fatal_error:
                restart_count += 1
                logger.error(
                    f"[ERROR] SLE worker crashed (restart {restart_count}/{max_restarts}): "
                    f"{fatal_error}",
                    exc_info=True
                )
                # Wait before restart to avoid rapid cycling
                time.sleep(5)
                logger.info("[...] SLE worker restarting after crash...")
        
        if restart_count >= max_restarts:
            logger.error(f"[FATAL] SLE worker exceeded {max_restarts} restarts - giving up")
        
        logger.info("[OK] SLE background collection loop ended")
    
    def _run_inner_loop(self, sle_collector) -> None:
        """Inner collection loop that can be restarted on errors."""
        while self._running:
            try:
                # Check rate limit before API calls
                if is_rate_limited():
                    rate_status = get_rate_limit_status()
                    remaining = rate_status.get("seconds_remaining", 60)
                    self._rate_limited = True
                    
                    logger.warning(
                        f"[RATE LIMIT] API rate limited - pausing SLE collection. "
                        f"Resume in {int(remaining // 60)}m {int(remaining % 60)}s"
                    )
                    time.sleep(min(60, int(remaining) + 1))
                    continue
                
                if self._rate_limited:
                    self._rate_limited = False
                    logger.info("[OK] Rate limit cleared - resuming SLE collection")
                
                self._collection_cycles += 1
                self._run_collection_cycle(sle_collector)
                
                # No delay - stay busy, immediately start next cycle
                
            except RateLimitError as rate_error:
                self._rate_limited = True
                wait_time = rate_error.seconds_remaining or 3600
                logger.error(
                    f"[RATE LIMIT] Hit 429 during SLE collection - pausing "
                    f"{int(wait_time // 60)}m {int(wait_time % 60)}s"
                )
                time.sleep(int(wait_time) + 5)
                
            except Exception as error:
                logger.error(f"[ERROR] SLE collection error: {error}", exc_info=True)
                # Brief yield to prevent CPU spin on repeated errors
                time.sleep(0.1)
    
    def _run_collection_cycle(self, sle_collector) -> None:
        """Execute one SLE collection cycle."""
        cycle_start = time.time()
        
        # Phase 1: Collect degraded sites first (priority)
        degraded_sites = self.data_provider.get_sle_degraded_sites()
        degraded_site_ids = set()
        
        if degraded_sites:
            # Count how many actually need collection (not fresh)
            sites_needing_collection = []
            for site in degraded_sites:
                site_id = site.get("site_id", "")
                if not self.cache.is_site_sle_cache_fresh(site_id, self.max_age_seconds):
                    sites_needing_collection.append(site)
                degraded_site_ids.add(site_id)
            
            if sites_needing_collection:
                logger.info(
                    f"[...] SLE cycle {self._collection_cycles}: "
                    f"Collecting {len(sites_needing_collection)} degraded sites "
                    f"({len(degraded_sites) - len(sites_needing_collection)} already fresh)"
                )
                
                for site in sites_needing_collection:
                    if not self._running:
                        break
                    
                    site_id = site.get("site_id", "")
                    site_name = site.get("site_name", "Unknown")
                    
                    self._current_site = site_name
                    result = sle_collector.collect_for_site(site_id, site_name)
                    
                    if result.success:
                        self._degraded_sites_collected += 1
                        self._total_sites_collected += 1
                    
                    if self.on_site_collected:
                        self.on_site_collected(result)
                    
                    # No delay - stay busy
            else:
                logger.debug(
                    f"[OK] SLE cycle {self._collection_cycles}: "
                    f"All {len(degraded_sites)} degraded sites already fresh"
                )
        
        # Get all sites for Phase 2 and 3
        all_sites = self._get_all_sites_list()
        all_site_ids = [s.get("site_id") for s in all_sites if s.get("site_id")]
        
        # Get cache status for logging
        sle_cache_status = self.cache.get_site_sle_cache_status(
            all_site_ids,
            self.max_age_seconds
        )
        
        # Phase 2: Backfill MISSING sites first (never collected - highest priority after degraded)
        missing_sites = self.cache.get_missing_sle_sites(all_site_ids)
        
        if missing_sites:
            batch_size = min(50, len(missing_sites))
            logger.info(
                f"[...] SLE Phase 2: Backfilling {batch_size} missing sites "
                f"({len(missing_sites)} total never-collected)"
            )
            
            for site_id in missing_sites[:batch_size]:
                if not self._running:
                    break
                
                site_name = self.data_provider.site_lookup.get(
                    site_id, site_id[:8] + "..."
                )
                
                self._current_site = site_name
                result = sle_collector.collect_for_site(site_id, site_name)
                
                if result.success:
                    self._total_sites_collected += 1
                
                if self.on_site_collected:
                    self.on_site_collected(result)
                
                # No delay - stay busy
        
        # Phase 3: Refresh STALE sites (already collected but old - lowest priority)
        # Only process stale if no missing sites remain
        if not missing_sites:
            stale_sites = self.cache.get_stale_sle_sites(
                all_site_ids,
                self.max_age_seconds
            )
            
            if stale_sites:
                batch_size = min(50, len(stale_sites))
                logger.info(
                    f"[...] SLE Phase 3: Refreshing {batch_size} stale sites "
                    f"({len(stale_sites)} total stale)"
                )
                
                for site_id in stale_sites[:batch_size]:
                    if not self._running:
                        break
                    
                    site_name = self.data_provider.site_lookup.get(
                        site_id, site_id[:8] + "..."
                    )
                    
                    self._current_site = site_name
                    result = sle_collector.collect_for_site(site_id, site_name)
                    
                    if result.success:
                        self._total_sites_collected += 1
                    
                    if self.on_site_collected:
                        self.on_site_collected(result)
                    
                    # No delay - stay busy
        
        # Log cycle summary
        cycle_duration = time.time() - cycle_start
        if self._collection_cycles % 10 == 0:
            logger.info(
                f"[INFO] SLE cycle {self._collection_cycles}: "
                f"{sle_cache_status['fresh']} fresh, {sle_cache_status['stale']} stale, "
                f"{sle_cache_status['missing']} missing ({cycle_duration:.1f}s)"
            )
    
    def _get_all_sites_list(self) -> List[Dict[str, Any]]:
        """Get list of all sites from data provider."""
        if hasattr(self.data_provider, 'sle_data') and self.data_provider.sle_data:
            return [
                {"site_id": r.get("site_id"), "site_name": self.data_provider.site_lookup.get(r.get("site_id"), "Unknown")}
                for r in self.data_provider.sle_data.get("results", [])
            ]
        return []
    
    def get_status(self) -> Dict[str, Any]:
        """Get current worker status for monitoring."""
        return {
            "running": self._running,
            "collection_cycles": self._collection_cycles,
            "total_sites_collected": self._total_sites_collected,
            "degraded_sites_collected": self._degraded_sites_collected,
            "current_site": self._current_site,
            "min_delay_seconds": self.min_delay,
            "max_age_seconds": self.max_age_seconds,
            "rate_limited": self._rate_limited
        }
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running


# ============================================================================
# VPN Peer Path Background Collector
# ============================================================================


class VPNPeerBackgroundWorker:
    """
    Background worker for collecting VPN peer path statistics.
    
    Collects loss, latency, jitter, and MOS scores for VPN peer paths
    across all gateways in the organization. Data is cached in Redis
    for display on the dashboard.
    """
    
    def __init__(
        self,
        cache,
        api_client,
        min_delay_between_fetches: int = 5,
        refresh_interval_seconds: int = 300,
        on_data_updated: Optional[Callable] = None
    ):
        """
        Initialize the VPN peer background worker.
        
        Args:
            cache: Redis cache instance
            api_client: Mist API client instance
            min_delay_between_fetches: Minimum seconds between API calls
            refresh_interval_seconds: How often to refresh all data (default: 5 min)
            on_data_updated: Optional callback when data is refreshed
        """
        self.cache = cache
        self.api_client = api_client
        self.min_delay = min_delay_between_fetches
        self.refresh_interval = refresh_interval_seconds
        self.on_data_updated = on_data_updated
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._total_peers_collected = 0
        self._collection_cycles = 0
        self._rate_limited = False
        self._last_collection_time: float = 0
    
    def start(self) -> None:
        """Start the VPN peer background worker."""
        if self._running:
            logger.warning("[WARN] VPN peer background worker already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._collection_loop,
            daemon=True,
            name="VPNPeerBackgroundWorker"
        )
        self._thread.start()
        logger.info("[OK] VPN peer background worker started")
    
    def stop(self) -> None:
        """Stop the VPN peer background worker."""
        if not self._running:
            return
        
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        
        logger.info(
            f"[OK] VPN peer background worker stopped "
            f"(collected {self._total_peers_collected} peers in "
            f"{self._collection_cycles} cycles)"
        )
    
    def _collection_loop(self) -> None:
        """Main collection loop - runs continuously with auto-restart on errors."""
        logger.info("[...] VPN peer background collection starting")
        
        restart_count = 0
        max_restarts = 100  # Allow many restarts before giving up
        
        while self._running and restart_count < max_restarts:
            try:
                self._run_inner_vpn_loop()
                
            except Exception as fatal_error:
                restart_count += 1
                logger.error(
                    f"[ERROR] VPN worker crashed (restart {restart_count}/{max_restarts}): "
                    f"{fatal_error}",
                    exc_info=True
                )
                # Wait before restart to avoid rapid cycling
                time.sleep(5)
                logger.info("[...] VPN worker restarting after crash...")
        
        if restart_count >= max_restarts:
            logger.error(f"[FATAL] VPN worker exceeded {max_restarts} restarts - giving up")
        
        logger.info("[OK] VPN peer background collection loop ended")
    
    def _run_inner_vpn_loop(self) -> None:
        """Inner collection loop that can be restarted on errors."""
        while self._running:
            try:
                # Check rate limit before API calls
                if is_rate_limited():
                    rate_status = get_rate_limit_status()
                    remaining = rate_status.get("seconds_remaining", 60)
                    self._rate_limited = True
                    
                    logger.warning(
                        f"[RATE LIMIT] API rate limited - pausing VPN collection. "
                        f"Resume in {int(remaining // 60)}m {int(remaining % 60)}s"
                    )
                    time.sleep(min(60, int(remaining) + 1))
                    continue
                
                if self._rate_limited:
                    self._rate_limited = False
                    logger.info("[OK] Rate limit cleared - resuming VPN collection")
                
                # No refresh interval check - stay busy, always collect
                self._collection_cycles += 1
                self._run_collection_cycle()
                
                # No delay - immediately start next cycle
                
            except RateLimitError as rate_error:
                self._rate_limited = True
                wait_time = rate_error.seconds_remaining or 3600
                logger.error(
                    f"[RATE LIMIT] Hit 429 during VPN collection - pausing "
                    f"{int(wait_time // 60)}m {int(wait_time % 60)}s"
                )
                time.sleep(int(wait_time) + 5)
                
            except Exception as error:
                logger.error(f"[ERROR] VPN collection error: {error}", exc_info=True)
                # Brief yield to prevent CPU spin on repeated errors
                time.sleep(0.1)
    
    def _run_collection_cycle(self) -> None:
        """Execute one VPN peer collection cycle."""
        cycle_start = time.time()
        
        logger.info(f"[...] VPN peer cycle {self._collection_cycles}: Starting collection")
        
        try:
            # Fetch all VPN peer stats from the org-level endpoint
            result = self.api_client.get_org_vpn_peer_stats()
            
            if result.get("success"):
                peers_by_port = result.get("peers_by_port", {})
                total_peers = result.get("total_peers", 0)
                
                # Group peers by gateway (mac address from peer records)
                peers_by_gateway: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
                
                for port_id, peers_list in peers_by_port.items():
                    for peer in peers_list:
                        mac = peer.get("mac", "unknown")
                        site_id = peer.get("site_id", "")
                        cache_key = f"{site_id}:{mac}" if site_id else mac
                        
                        if cache_key not in peers_by_gateway:
                            peers_by_gateway[cache_key] = {}
                        
                        if port_id not in peers_by_gateway[cache_key]:
                            peers_by_gateway[cache_key][port_id] = []
                        
                        peers_by_gateway[cache_key][port_id].append(peer)
                
                # Save all peers to cache in one operation
                self.cache.save_all_vpn_peers(peers_by_gateway)
                
                self._total_peers_collected += total_peers
                self._last_collection_time = time.time()
                
                # Call update callback if provided
                if self.on_data_updated:
                    self.on_data_updated({
                        "total_peers": total_peers,
                        "gateways_with_peers": len(peers_by_gateway)
                    })
                
                cycle_duration = time.time() - cycle_start
                logger.info(
                    f"[OK] VPN peer cycle {self._collection_cycles} complete: "
                    f"{total_peers} peers from {len(peers_by_gateway)} gateways "
                    f"in {cycle_duration:.1f}s"
                )
            
            elif result.get("rate_limited"):
                logger.warning("[RATE LIMIT] VPN peer stats rate limited")
                self._rate_limited = True
            
            else:
                error_msg = result.get("error", "Unknown error")
                logger.warning(f"[WARN] VPN peer collection failed: {error_msg}")
                
        except Exception as error:
            logger.error(f"[ERROR] VPN peer collection cycle failed: {error}", exc_info=True)
    
    def get_status(self) -> Dict[str, Any]:
        """Get current worker status for monitoring."""
        return {
            "running": self._running,
            "collection_cycles": self._collection_cycles,
            "total_peers_collected": self._total_peers_collected,
            "last_collection_time": self._last_collection_time,
            "refresh_interval_seconds": self.refresh_interval,
            "min_delay_seconds": self.min_delay,
            "rate_limited": self._rate_limited
        }
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running