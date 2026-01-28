"""
MistWANPerformance - Background Cache Refresh

Continuously refreshes stale cache data in the background while
the dashboard is running. Prioritizes oldest data first.

NASA/JPL Pattern: Safety-first with graceful degradation.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class BackgroundRefreshWorker:
    """
    Background worker that refreshes stale cache data.
    
    Runs in a separate thread, periodically checking for stale
    sites and fetching fresh data from the API. Oldest data
    gets priority to ensure no site is neglected.
    """
    
    def __init__(
        self,
        cache,
        api_client,
        site_ids: List[str],
        refresh_interval_seconds: int = 300,
        max_sites_per_cycle: int = 50,
        max_age_seconds: int = 3600,
        on_data_updated: Optional[Callable] = None
    ):
        """
        Initialize the background refresh worker.
        
        Args:
            cache: Redis cache instance
            api_client: Mist API client instance
            site_ids: List of all site IDs to monitor
            refresh_interval_seconds: How often to check for stale data (default: 5 min)
            max_sites_per_cycle: Max sites to refresh per cycle (default: 50)
            max_age_seconds: Cache age threshold for staleness (default: 1 hour)
            on_data_updated: Optional callback when data is refreshed
        """
        self.cache = cache
        self.api_client = api_client
        self.site_ids = site_ids
        self.refresh_interval = refresh_interval_seconds
        self.max_sites_per_cycle = max_sites_per_cycle
        self.max_age_seconds = max_age_seconds
        self.on_data_updated = on_data_updated
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_refresh_time = 0
        self._total_sites_refreshed = 0
        self._refresh_cycles = 0
    
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
            f"(interval: {self.refresh_interval}s, max sites/cycle: {self.max_sites_per_cycle})"
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
        """Main refresh loop - runs in background thread."""
        logger.info("[...] Background refresh loop starting")
        
        while self._running:
            try:
                self._run_refresh_cycle()
            except Exception as error:
                logger.error(f"[ERROR] Background refresh error: {error}", exc_info=True)
            
            # Sleep until next refresh interval
            self._interruptible_sleep(self.refresh_interval)
    
    def _interruptible_sleep(self, seconds: int) -> None:
        """Sleep that can be interrupted by stop()."""
        end_time = time.time() + seconds
        while self._running and time.time() < end_time:
            time.sleep(1)  # Check every second if we should stop
    
    def _run_refresh_cycle(self) -> None:
        """Execute one refresh cycle."""
        self._refresh_cycles += 1
        cycle_start = time.time()
        
        # Get oldest stale sites
        stale_sites = self.cache.get_oldest_stale_sites(
            self.site_ids,
            max_age_seconds=self.max_age_seconds,
            limit=self.max_sites_per_cycle
        )
        
        if not stale_sites:
            logger.debug(
                f"[OK] Refresh cycle {self._refresh_cycles}: "
                f"All {len(self.site_ids)} sites fresh"
            )
            return
        
        logger.info(
            f"[...] Refresh cycle {self._refresh_cycles}: "
            f"Refreshing {len(stale_sites)} oldest stale sites"
        )
        
        # Fetch fresh data from API for all sites
        # (API returns all data, we filter to stale sites)
        try:
            all_port_stats = self.api_client.get_org_gateway_port_stats()
            
            if not all_port_stats:
                logger.warning("[WARN] API returned no port stats")
                return
            
            # Filter to only stale sites
            stale_set = set(stale_sites)
            fresh_stats = [
                port for port in all_port_stats
                if port.get("site_id") in stale_set
            ]
            
            if fresh_stats:
                # Update cache for refreshed sites
                sites_cached = self.cache.set_bulk_site_port_stats(fresh_stats)
                self._total_sites_refreshed += sites_cached
                
                cycle_duration = time.time() - cycle_start
                logger.info(
                    f"[OK] Refresh cycle {self._refresh_cycles} complete: "
                    f"{sites_cached} sites refreshed in {cycle_duration:.1f}s"
                )
                
                # Notify callback if provided
                if self.on_data_updated:
                    try:
                        self.on_data_updated(fresh_stats)
                    except Exception as callback_error:
                        logger.error(f"[ERROR] Data update callback failed: {callback_error}")
            else:
                logger.warning(
                    f"[WARN] No port stats found for {len(stale_sites)} stale sites"
                )
        
        except Exception as api_error:
            logger.error(f"[ERROR] API fetch failed in refresh cycle: {api_error}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current worker status for monitoring."""
        return {
            "running": self._running,
            "refresh_cycles": self._refresh_cycles,
            "total_sites_refreshed": self._total_sites_refreshed,
            "last_refresh_time": self._last_refresh_time,
            "refresh_interval_seconds": self.refresh_interval,
            "max_sites_per_cycle": self.max_sites_per_cycle,
            "max_age_seconds": self.max_age_seconds,
            "monitored_site_count": len(self.site_ids)
        }
    
    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._running
