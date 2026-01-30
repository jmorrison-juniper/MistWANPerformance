"""
MistWANPerformance - Site-Level SLE Collector

Collects detailed SLE (Service Level Experience) metrics for WAN Link Health
at the site level. Supports prioritized collection (degraded sites first)
with Redis caching for incremental updates.

Endpoints used:
- /sites/{site_id}/sle/site/{site_id}/metric/wan-link-health/summary
- /sites/{site_id}/sle/site/{site_id}/metric/wan-link-health/histogram
- /sites/{site_id}/sle/site/{site_id}/metric/wan-link-health/impacted-gateways
- /sites/{site_id}/sle/site/{site_id}/metric/wan-link-health/impacted-interfaces
- /sites/{site_id}/sle/site/{site_id}/metric/wan-link-health/threshold
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.api.mist_client import MistAPIClient
from src.cache.redis_cache import RedisCache


logger = logging.getLogger(__name__)

# Default metric for WAN performance monitoring
DEFAULT_METRIC = "wan-link-health"

# Cache TTL: 7 days in seconds (matches SLE data retention)
CACHE_TTL_SECONDS = 7 * 24 * 3600

# Max age before refresh: 1 hour (10-minute resolution means hourly refresh is reasonable)
MAX_CACHE_AGE_SECONDS = 3600


@dataclass
class SLECollectionResult:
    """Result from collecting SLE data for a site."""
    
    site_id: str
    site_name: str
    success: bool
    summary_collected: bool
    histogram_collected: bool
    gateways_collected: bool
    interfaces_collected: bool
    error_message: Optional[str] = None
    collection_time_ms: int = 0


class SLECollector:
    """
    Collector for site-level SLE (Service Level Experience) data.
    
    Collects detailed WAN Link Health metrics including:
    - Time-series summary with classifier breakdown
    - Score distribution histogram
    - Impacted gateways with degradation percentages
    - Impacted interfaces with degradation details
    """
    
    def __init__(
        self,
        api_client: MistAPIClient,
        cache: RedisCache,
        metric: str = DEFAULT_METRIC
    ):
        """
        Initialize the SLE collector.
        
        Args:
            api_client: Initialized Mist API client
            cache: Redis cache instance for data persistence
            metric: SLE metric to collect (default: wan-link-health)
        """
        self.api_client = api_client
        self.cache = cache
        self.metric = metric
        logger.debug(f"SLECollector initialized for metric: {metric}")
    
    def collect_for_site(
        self,
        site_id: str,
        site_name: str = "Unknown",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1w"
    ) -> SLECollectionResult:
        """
        Collect all SLE data for a single site.
        
        Args:
            site_id: Mist site UUID
            site_name: Site name for logging
            start_time: Unix timestamp for start (optional)
            end_time: Unix timestamp for end (optional)
            duration: Time duration string (default: 1w for 1 week)
        
        Returns:
            SLECollectionResult with collection status
        """
        start_ms = int(time.time() * 1000)
        result = SLECollectionResult(
            site_id=site_id,
            site_name=site_name,
            success=False,
            summary_collected=False,
            histogram_collected=False,
            gateways_collected=False,
            interfaces_collected=False
        )
        
        logger.info(f"[...] Collecting SLE data for site: {site_name} ({site_id})")
        
        try:
            # Collect summary (time-series with classifiers)
            result.summary_collected = self._collect_summary(
                site_id, start_time, end_time, duration
            )
            
            # Collect histogram (score distribution)
            result.histogram_collected = self._collect_histogram(
                site_id, start_time, end_time, duration
            )
            
            # Collect impacted gateways
            result.gateways_collected = self._collect_impacted_gateways(
                site_id, start_time, end_time, duration
            )
            
            # Collect impacted interfaces
            result.interfaces_collected = self._collect_impacted_interfaces(
                site_id, start_time, end_time, duration
            )
            
            # Update last fetch timestamp
            self._update_last_fetch_timestamp(site_id)
            
            # Mark success if at least summary was collected
            result.success = result.summary_collected
            
        except Exception as error:
            logger.error(f"[ERROR] Failed to collect SLE for site {site_name}: {error}")
            result.error_message = str(error)
        
        result.collection_time_ms = int(time.time() * 1000) - start_ms
        return result
    
    def _collect_summary(
        self,
        site_id: str,
        start_time: Optional[int],
        end_time: Optional[int],
        duration: str
    ) -> bool:
        """Collect and cache SLE summary data."""
        try:
            summary_data = self.api_client.get_site_sle_summary(
                site_id=site_id,
                metric=self.metric,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
            
            if summary_data:
                self.cache.save_site_sle_summary(
                    site_id=site_id,
                    metric=self.metric,
                    summary_data=summary_data,
                    ttl=CACHE_TTL_SECONDS
                )
                logger.debug(f"Saved SLE summary for site {site_id}")
                return True
            
            return False
            
        except Exception as error:
            logger.warning(f"Failed to collect SLE summary for {site_id}: {error}")
            return False
    
    def _collect_histogram(
        self,
        site_id: str,
        start_time: Optional[int],
        end_time: Optional[int],
        duration: str
    ) -> bool:
        """Collect and cache SLE histogram data."""
        try:
            histogram_data = self.api_client.get_site_sle_histogram(
                site_id=site_id,
                metric=self.metric,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
            
            if histogram_data:
                self.cache.save_site_sle_histogram(
                    site_id=site_id,
                    metric=self.metric,
                    histogram_data=histogram_data,
                    ttl=CACHE_TTL_SECONDS
                )
                logger.debug(f"Saved SLE histogram for site {site_id}")
                return True
            
            return False
            
        except Exception as error:
            logger.warning(f"Failed to collect SLE histogram for {site_id}: {error}")
            return False
    
    def _collect_impacted_gateways(
        self,
        site_id: str,
        start_time: Optional[int],
        end_time: Optional[int],
        duration: str
    ) -> bool:
        """Collect and cache impacted gateways data."""
        try:
            gateways_data = self.api_client.get_site_sle_impacted_gateways(
                site_id=site_id,
                metric=self.metric,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
            
            if gateways_data:
                self.cache.save_site_sle_impacted_gateways(
                    site_id=site_id,
                    metric=self.metric,
                    gateways_data=gateways_data,
                    ttl=CACHE_TTL_SECONDS
                )
                logger.debug(f"Saved impacted gateways for site {site_id}")
                return True
            
            return False
            
        except Exception as error:
            logger.warning(f"Failed to collect impacted gateways for {site_id}: {error}")
            return False
    
    def _collect_impacted_interfaces(
        self,
        site_id: str,
        start_time: Optional[int],
        end_time: Optional[int],
        duration: str
    ) -> bool:
        """Collect and cache impacted interfaces data."""
        try:
            interfaces_data = self.api_client.get_site_sle_impacted_interfaces(
                site_id=site_id,
                metric=self.metric,
                start_time=start_time,
                end_time=end_time,
                duration=duration
            )
            
            if interfaces_data:
                self.cache.save_site_sle_impacted_interfaces(
                    site_id=site_id,
                    metric=self.metric,
                    interfaces_data=interfaces_data,
                    ttl=CACHE_TTL_SECONDS
                )
                logger.debug(f"Saved impacted interfaces for site {site_id}")
                return True
            
            return False
            
        except Exception as error:
            logger.warning(f"Failed to collect impacted interfaces for {site_id}: {error}")
            return False
    
    def _update_last_fetch_timestamp(self, site_id: str) -> None:
        """Update the last fetch timestamp for incremental updates."""
        timestamp = int(datetime.now(timezone.utc).timestamp())
        key = f"{self.cache.PREFIX_SITE_SLE}:last_fetch:{site_id}"
        try:
            self.cache.client.set(key, str(timestamp), ex=CACHE_TTL_SECONDS)
        except Exception as error:
            logger.warning(f"Failed to update last fetch timestamp: {error}")
    
    def collect_for_degraded_sites(
        self,
        degraded_sites: List[Dict[str, Any]],
        max_sites: Optional[int] = None
    ) -> Tuple[int, int, List[SLECollectionResult]]:
        """
        Collect SLE data for degraded sites (priority collection).
        
        Args:
            degraded_sites: List of degraded site dicts with 'site_id' and 'site_name'
            max_sites: Maximum sites to process (None for all)
        
        Returns:
            Tuple of (success_count, failure_count, results_list)
        """
        sites_to_process = degraded_sites[:max_sites] if max_sites else degraded_sites
        
        logger.info(f"[...] Collecting SLE for {len(sites_to_process)} degraded sites")
        
        success_count = 0
        failure_count = 0
        results = []
        
        for index, site in enumerate(sites_to_process, 1):
            site_id = site.get("site_id", "")
            site_name = site.get("site_name", "Unknown")
            
            logger.info(f"[...] Processing site {index}/{len(sites_to_process)}: {site_name}")
            
            result = self.collect_for_site(site_id, site_name)
            results.append(result)
            
            if result.success:
                success_count += 1
            else:
                failure_count += 1
            
            # Brief pause to respect API rate limits
            time.sleep(0.2)
        
        logger.info(
            f"[DONE] Degraded sites collection complete: "
            f"{success_count} success, {failure_count} failed"
        )
        
        return success_count, failure_count, results
    
    def collect_for_all_sites(
        self,
        all_sites: List[Dict[str, Any]],
        max_age_seconds: int = MAX_CACHE_AGE_SECONDS,
        max_sites: Optional[int] = None
    ) -> Tuple[int, int, int, List[SLECollectionResult]]:
        """
        Collect SLE data for all sites, skipping fresh cache entries.
        
        Args:
            all_sites: List of all site dicts with 'site_id' and 'site_name'
            max_age_seconds: Skip sites with cache fresher than this
            max_sites: Maximum sites to process (None for all)
        
        Returns:
            Tuple of (success_count, failure_count, skipped_count, results_list)
        """
        # Get sites that need refresh
        site_ids = [site.get("site_id", "") for site in all_sites if site.get("site_id")]
        sites_needing_refresh = set(
            self.cache.get_sites_needing_sle_refresh(site_ids, max_age_seconds)
        )
        
        # Build list of sites to process
        sites_to_process = [
            site for site in all_sites
            if site.get("site_id") in sites_needing_refresh
        ]
        
        if max_sites:
            sites_to_process = sites_to_process[:max_sites]
        
        skipped_count = len(all_sites) - len(sites_to_process)
        
        logger.info(
            f"[...] Collecting SLE for {len(sites_to_process)} sites "
            f"(skipping {skipped_count} with fresh cache)"
        )
        
        success_count = 0
        failure_count = 0
        results = []
        
        for index, site in enumerate(sites_to_process, 1):
            site_id = site.get("site_id", "")
            site_name = site.get("site_name", "Unknown")
            
            if index % 50 == 0 or index == 1:
                logger.info(
                    f"[...] Progress: {index}/{len(sites_to_process)} sites processed"
                )
            
            result = self.collect_for_site(site_id, site_name)
            results.append(result)
            
            if result.success:
                success_count += 1
            else:
                failure_count += 1
            
            # Brief pause to respect API rate limits
            time.sleep(0.1)
        
        logger.info(
            f"[DONE] All sites collection complete: "
            f"{success_count} success, {failure_count} failed, {skipped_count} skipped"
        )
        
        return success_count, failure_count, skipped_count, results
    
    def get_cached_site_data(self, site_id: str) -> Dict[str, Any]:
        """
        Retrieve all cached SLE data for a site.
        
        Args:
            site_id: Mist site UUID
        
        Returns:
            Dict with summary, histogram, gateways, interfaces data
        """
        return {
            "summary": self.cache.get_site_sle_summary(site_id, self.metric),
            "histogram": self.cache.get_site_sle_histogram(site_id, self.metric),
            "impacted_gateways": self.cache.get_site_sle_impacted_gateways(
                site_id, self.metric
            ),
            "impacted_interfaces": self.cache.get_site_sle_impacted_interfaces(
                site_id, self.metric
            ),
            "last_fetch": self.cache.get_last_site_sle_timestamp(site_id),
            "cache_fresh": self.cache.is_site_sle_cache_fresh(
                site_id, MAX_CACHE_AGE_SECONDS
            )
        }
