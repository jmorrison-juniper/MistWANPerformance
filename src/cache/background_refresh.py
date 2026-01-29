"""
MistWANPerformance - Background Cache Refresh

Continuously refreshes stale cache data in the background while
the dashboard is running. Prioritizes oldest data first.

NASA/JPL Pattern: Safety-first with graceful degradation.
Handles 429 rate limits by pausing until top of hour reset.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.api.mist_client import RateLimitError, get_rate_limit_status, is_rate_limited

logger = logging.getLogger(__name__)


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
                
                # Ensure minimum delay between API calls (rate limit protection)
                if cycle_duration < self.min_delay:
                    sleep_time = self.min_delay - cycle_duration
                    self._interruptible_sleep(sleep_time)
                    
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
                # Brief pause on error before retry
                self._interruptible_sleep(5)
    
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
