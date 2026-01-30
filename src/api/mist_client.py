"""
MistWANPerformance - Mist API Client

This module provides a client for interacting with the Juniper Mist Cloud API,
specifically for WAN circuit performance data collection.

Split into focused classes per 5-item rule:
- MistConnection: Session management and rate limiting
- MistSiteOperations: Site and device retrieval
- MistStatsOperations: Statistics and events retrieval
- MistAPIClient: Facade maintaining backward compatibility- RateLimitState: Global rate limit tracking (429 handling)"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Union

# Mist API SDK import with graceful fallback
MIST_API_AVAILABLE = False
try:
    import mistapi
    from mistapi import APISession
    MIST_API_AVAILABLE = True
except ImportError:
    mistapi = None  # type: ignore[assignment]
    APISession = None  # type: ignore[assignment, misc]

from src.utils.config import MistConfig, OperationalConfig


logger = logging.getLogger(__name__)


class RateLimitState:
    """
    Global rate limit state tracking for 429 handling.
    
    Mist API rate limits reset at the top of each hour.
    When a 429 is detected, all API calls pause until reset.
    
    Thread-safe singleton pattern for use across all API clients.
    """
    _instance = None
    _lock = None
    
    def __new__(cls):
        if cls._instance is None:
            import threading
            cls._lock = threading.Lock()
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.rate_limited = False
        self.rate_limit_hit_time: Optional[float] = None
        self.rate_limit_reset_time: Optional[float] = None
        self._hit_count = 0
    
    def set_rate_limited(self) -> float:
        """
        Mark that we hit a 429 rate limit.
        
        Returns:
            Seconds until the top of the next hour (reset time)
        """
        with self._lock:
            self.rate_limited = True
            self.rate_limit_hit_time = time.time()
            self._hit_count += 1
            
            # Calculate seconds until top of next hour
            now = datetime.now()
            minutes_until_reset = 60 - now.minute
            seconds_until_reset = (minutes_until_reset * 60) - now.second
            
            # Add small buffer to ensure we're past the reset
            seconds_until_reset = max(seconds_until_reset, 60) + 5
            
            self.rate_limit_reset_time = time.time() + seconds_until_reset
            
            logger.error(
                f"[RATE LIMIT] API rate limit (429) hit! "
                f"Count: {self._hit_count}. "
                f"Pausing ALL API calls for {seconds_until_reset // 60:.0f} min "
                f"{seconds_until_reset % 60:.0f} sec until top of hour."
            )
            
            return seconds_until_reset
    
    def check_and_clear(self) -> bool:
        """
        Check if rate limit has expired and clear if so.
        
        Returns:
            True if currently rate limited, False if clear
        """
        with self._lock:
            if not self.rate_limited:
                return False
            
            if time.time() >= self.rate_limit_reset_time:
                self.rate_limited = False
                self.rate_limit_hit_time = None
                self.rate_limit_reset_time = None
                logger.info("[OK] API rate limit period expired - resuming operations")
                return False
            
            return True
    
    def seconds_until_reset(self) -> Optional[float]:
        """Get seconds remaining until rate limit resets."""
        with self._lock:
            if not self.rate_limited or not self.rate_limit_reset_time:
                return None
            return max(0, self.rate_limit_reset_time - time.time())
    
    def get_status(self) -> Dict[str, Any]:
        """Get current rate limit status for status bar display."""
        with self._lock:
            if not self.rate_limited:
                return {
                    "rate_limited": False,
                    "hit_count": self._hit_count,
                    "status_text": "OK",
                    "status_color": "healthy"
                }
            
            remaining = self.seconds_until_reset()
            if remaining:
                minutes = int(remaining // 60)
                seconds = int(remaining % 60)
                return {
                    "rate_limited": True,
                    "hit_count": self._hit_count,
                    "seconds_remaining": remaining,
                    "status_text": f"RATE LIMITED - Resume in {minutes}m {seconds}s",
                    "status_color": "critical"
                }
            else:
                return {
                    "rate_limited": True,
                    "hit_count": self._hit_count,
                    "status_text": "RATE LIMITED - Checking...",
                    "status_color": "warning"
                }


# Global singleton instance
_rate_limit_state = RateLimitState()


class RateLimitError(Exception):
    """
    Exception raised when API rate limit (429) is hit.
    
    Callers should catch this and wait until seconds_remaining expires.
    """
    def __init__(self, message: str, seconds_remaining: Optional[float] = None):
        super().__init__(message)
        self.seconds_remaining = seconds_remaining


def get_rate_limit_status() -> Dict[str, Any]:
    """
    Get the current rate limit status for external consumers (e.g., dashboard).
    
    Returns:
        Dict with rate_limited (bool), status_text, status_color, etc.
    """
    return _rate_limit_state.get_status()


def is_rate_limited() -> bool:
    """Check if API is currently rate limited."""
    return _rate_limit_state.check_and_clear()


class MistConnection:
    """
    Manages Mist API session lifecycle and rate limiting.
    
    Responsibilities:
    - Initialize and maintain API session
    - Apply rate limiting between requests
    - Execute API calls with retry logic
    """
    
    def __init__(self, mist_config: MistConfig, operational_config: OperationalConfig):
        """
        Initialize the Mist connection manager.
        
        Args:
            mist_config: Mist API configuration (token, org_id, host)
            operational_config: Operational settings (rate limits, retries)
        
        Raises:
            ImportError: If mistapi package is not installed
        """
        if not MIST_API_AVAILABLE:
            raise ImportError(
                "mistapi package is required. Install with: pip install mistapi"
            )
        
        self.config = mist_config
        self.ops_config = operational_config
        self.session: Any = None
        self._last_request_time = 0.0
        
        logger.info("[INFO] Initializing Mist API connection")
        self._initialize_session()
    
    def _initialize_session(self) -> None:
        """Initialize the Mist API session."""
        try:
            self.session = APISession(  # type: ignore[misc]
                host=self.config.api_host,
                apitoken=self.config.api_token
            )
            logger.debug("Mist API session initialized successfully")
        except Exception as error:
            logger.error(f"[ERROR] Failed to initialize Mist API session: {error}")
            raise
    
    def apply_rate_limit(self) -> None:
        """Apply rate limiting between API requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.ops_config.rate_limit_delay:
            sleep_time = self.ops_config.rate_limit_delay - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.time()
    
    def execute_with_retry(
        self,
        operation: str,
        api_call: Callable[..., Any],
        *args: Any,
        **kwargs: Any
    ) -> Any:
        """
        Execute an API call with retry logic and 429 rate limit handling.
        
        Args:
            operation: Description of the operation (for logging)
            api_call: Callable API method
            *args: Positional arguments for API call
            **kwargs: Keyword arguments for API call
        
        Returns:
            API response data
        
        Raises:
            RateLimitError: If rate limited (429) - caller should wait
            Exception: If all retries are exhausted
        """
        # Check if we're currently rate limited before trying
        if _rate_limit_state.check_and_clear():
            remaining = _rate_limit_state.seconds_until_reset()
            raise RateLimitError(
                f"API rate limited. {remaining:.0f}s remaining until reset.",
                seconds_remaining=remaining
            )
        
        last_error: Optional[Exception] = None
        
        for attempt in range(1, self.ops_config.max_retries + 1):
            try:
                self.apply_rate_limit()
                response = api_call(*args, **kwargs)
                return response
            except Exception as error:
                last_error = error
                error_str = str(error).lower()
                
                # Check for 429 rate limit error
                if self._is_rate_limit_error(error):
                    seconds_wait = _rate_limit_state.set_rate_limited()
                    raise RateLimitError(
                        f"API rate limit (429) hit. Waiting {seconds_wait:.0f}s until top of hour.",
                        seconds_remaining=seconds_wait
                    )
                
                logger.warning(
                    f"[WARN] {operation} failed (attempt {attempt}/{self.ops_config.max_retries}): {error}"
                )
                if attempt < self.ops_config.max_retries:
                    time.sleep(self.ops_config.retry_delay * attempt)
        
        logger.error(f"[ERROR] {operation} failed after {self.ops_config.max_retries} attempts")
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{operation} failed with unknown error")
    
    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an exception indicates a 429 rate limit error."""
        error_str = str(error).lower()
        
        # Check for common 429 indicators
        if "429" in error_str:
            return True
        if "rate limit" in error_str:
            return True
        if "too many requests" in error_str:
            return True
        
        # Check for response status code attribute
        if hasattr(error, 'response'):
            response = error.response
            if hasattr(response, 'status_code') and response.status_code == 429:
                return True
        
        # Check for status_code attribute directly
        if hasattr(error, 'status_code') and error.status_code == 429:
            return True
        
        return False
    
    def close(self) -> None:
        """Close the API session and clean up resources."""
        logger.debug("Closing Mist API connection")
        self.session = None


class MistSiteOperations:
    """
    Handles site and device retrieval operations.
    
    Responsibilities:
    - Get organization sites
    - Get WAN edge devices for sites
    - Test API connectivity
    """
    
    def __init__(self, connection: MistConnection):
        """
        Initialize site operations.
        
        Args:
            connection: MistConnection instance for API access
        """
        self.connection = connection
    
    def test_connection(self) -> bool:
        """
        Test the API connection by retrieving organization info.
        
        Returns:
            True if connection is successful
        """
        try:
            logger.info("[...] Testing Mist API connection")
            result = self.connection.execute_with_retry(
                "Get organization info",
                mistapi.api.v1.orgs.orgs.getOrg,  # type: ignore[union-attr]
                self.connection.session,
                self.connection.config.org_id
            )
            logger.info("[OK] Mist API connection successful")
            logger.debug(f"Organization: {result.data.get('name', 'Unknown')}")
            return True
        except Exception as error:
            logger.error(f"[ERROR] Mist API connection failed: {error}")
            return False
    
    def get_sites(self) -> List[Dict[str, Any]]:
        """
        Get all sites in the organization.
        
        Returns:
            List of site dictionaries
        """
        logger.info("[...] Retrieving organization sites")
        
        sites = []
        page = 1
        
        while True:
            response = self.connection.execute_with_retry(
                f"Get sites (page {page})",
                mistapi.api.v1.orgs.sites.listOrgSites,  # type: ignore[union-attr]
                self.connection.session,
                self.connection.config.org_id,
                limit=1000,
                page=page
            )
            
            batch = response.data if hasattr(response, 'data') else []
            sites.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} sites from page {page}")
            
            if len(batch) < 1000:
                break
            page += 1
        
        logger.info(f"[OK] Retrieved {len(sites)} total sites")
        return sites
    
    def get_site_groups(self) -> Dict[str, str]:
        """
        Get all site groups in the organization with their human-readable names.
        
        Returns:
            Dictionary mapping sitegroup_id to sitegroup_name
        """
        logger.info("[...] Retrieving organization site groups")
        
        sitegroup_map = {}
        page = 1
        
        while True:
            response = self.connection.execute_with_retry(
                f"Get site groups (page {page})",
                mistapi.api.v1.orgs.sitegroups.listOrgSiteGroups,  # type: ignore[union-attr]
                self.connection.session,
                self.connection.config.org_id,
                limit=1000,
                page=page
            )
            
            batch = response.data if hasattr(response, 'data') else []
            
            for group in batch:
                group_id = group.get('id', '')
                group_name = group.get('name', 'Unknown')
                if group_id:
                    sitegroup_map[group_id] = group_name
            
            logger.debug(f"Retrieved {len(batch)} site groups from page {page}")
            
            if len(batch) < 1000:
                break
            page += 1
        
        logger.info(f"[OK] Retrieved {len(sitegroup_map)} site groups")
        return sitegroup_map
    
    def get_site_wan_edges(self, site_id: str) -> List[Dict[str, Any]]:
        """
        Get WAN edge devices (gateways) for a specific site.
        
        Args:
            site_id: Mist site UUID
        
        Returns:
            List of WAN edge device dictionaries
        """
        logger.debug(f"Retrieving WAN edges for site {site_id}")
        
        response = self.connection.execute_with_retry(
            f"Get WAN edges for site {site_id}",
            mistapi.api.v1.sites.devices.listSiteDevices,  # type: ignore[union-attr]
            self.connection.session,
            site_id,
            type="gateway",  # CRITICAL: Must specify type=gateway for WAN devices
            limit=1000
        )
        
        devices = response.data if hasattr(response, 'data') else []
        logger.debug(f"Found {len(devices)} WAN edge devices")
        return devices

    def get_gateway_inventory(self) -> Dict[str, Any]:
        """
        Get organization gateway inventory with connection status.
        
        Uses the org inventory API to retrieve all gateways and their
        connected/disconnected status.
        
        Returns:
            Dictionary with gateway counts:
            {
                "total": int,
                "connected": int,
                "disconnected": int,
                "gateways": List[Dict]  # Raw gateway inventory data
            }
        """
        logger.info("[...] Retrieving gateway inventory status")
        
        all_gateways = []
        page = 1
        
        while True:
            response = self.connection.execute_with_retry(
                f"Get gateway inventory (page {page})",
                mistapi.api.v1.orgs.inventory.getOrgInventory,  # type: ignore[union-attr]
                self.connection.session,
                self.connection.config.org_id,
                type="gateway",  # Filter to gateway devices only
                limit=1000,
                page=page
            )
            
            batch = response.data if hasattr(response, 'data') else []
            all_gateways.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} gateways from inventory page {page}")
            
            if len(batch) < 1000:
                break
            page += 1
        
        # Count connected vs disconnected
        connected_count = 0
        disconnected_count = 0
        
        for gateway in all_gateways:
            # The inventory API returns 'connected' as boolean
            is_connected = gateway.get("connected", False)
            if is_connected:
                connected_count += 1
            else:
                disconnected_count += 1
        
        result = {
            "total": len(all_gateways),
            "connected": connected_count,
            "disconnected": disconnected_count,
            "gateways": all_gateways
        }
        
        logger.info(
            f"[OK] Gateway inventory: {result['total']} total, "
            f"{result['connected']} connected, {result['disconnected']} disconnected"
        )
        return result


class MistStatsOperations:
    """
    Handles statistics and events retrieval operations.
    
    Responsibilities:
    - Get WAN edge device stats
    - Get WAN port stats (rx_bytes, tx_bytes, utilization)
    - Get WAN edge device events
    - Get organization device stats
    """
    
    def __init__(self, connection: MistConnection):
        """
        Initialize stats operations.
        
        Args:
            connection: MistConnection instance for API access
        """
        self.connection = connection
    
    def get_org_gateway_port_stats(
        self,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int, Optional[str]], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway port statistics.
        
        This is the primary method for getting real WAN utilization data.
        Returns rx_bytes, tx_bytes, speed, and status for all WAN ports.
        Fetches ALL available data with no batch limits.
        
        Args:
            on_batch: Optional callback function called after each batch.
                      Signature: on_batch(batch_records, batch_number, next_cursor)
                      Use this for incremental saves during long fetches.
        
        Returns:
            List of port statistics dictionaries
        """
        logger.info("[...] Retrieving organization gateway port stats (no limit)")
        
        all_ports = []
        search_after = None
        batch_count = 0
        
        while True:
            batch_count += 1
            response = self.connection.execute_with_retry(
                f"Get gateway port stats (batch {batch_count})",
                mistapi.api.v1.orgs.stats.searchOrgSwOrGwPorts,  # type: ignore[union-attr]
                self.connection.session,
                self.connection.config.org_id,
                type="gateway",  # CRITICAL: Filter to gateway devices only
                limit=1000,
                duration="1h",  # Last hour of data
                search_after=search_after
            )
            
            data = response.data if hasattr(response, 'data') else {}
            batch = data.get("results", [])
            all_ports.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} port stats in batch {batch_count}")
            
            # Check for more results (cursor-based pagination)
            next_cursor = data.get("next")
            
            # Call incremental save callback if provided
            if on_batch and batch:
                try:
                    on_batch(batch, batch_count, next_cursor)
                except Exception as callback_error:
                    logger.warning(f"[WARN] Batch callback failed: {callback_error}")
            
            if not next_cursor or len(batch) < 1000:
                break
            search_after = next_cursor
        
        logger.info(f"[OK] Retrieved {len(all_ports)} gateway port stats ({batch_count} batches, complete)")
        return all_ports
    
    def get_org_device_stats(self) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway device statistics.
        
        Returns basic gateway info: id, mac, name, site_id, status, uptime.
        
        Returns:
            List of device statistics dictionaries
        """
        logger.info("[...] Retrieving organization gateway device stats")
        
        all_devices = []
        page = 1
        
        while True:
            response = self.connection.execute_with_retry(
                f"Get gateway device stats (page {page})",
                mistapi.api.v1.orgs.stats.listOrgDevicesStats,  # type: ignore[union-attr]
                self.connection.session,
                self.connection.config.org_id,
                page=page,
                limit=1000,
                type="gateway"  # CRITICAL: Filter to gateway devices only
            )
            
            batch = response.data if hasattr(response, 'data') else []
            all_devices.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} device stats from page {page}")
            
            if len(batch) < 1000:
                break
            page += 1
        
        logger.info(f"[OK] Retrieved {len(all_devices)} gateway device stats")
        return all_devices
    
    def get_wan_edge_stats(
        self, 
        site_id: str, 
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get WAN edge device statistics including port utilization.
        
        Args:
            site_id: Mist site UUID
            device_id: WAN edge device UUID
            start_time: Optional start time for stats window
            end_time: Optional end time for stats window
        
        Returns:
            Device statistics dictionary
        """
        logger.debug(f"Retrieving stats for WAN edge {device_id}")
        
        api_kwargs: Dict[str, Union[str, int]] = {
            "site_id": site_id,
            "device_id": device_id
        }
        
        if start_time:
            api_kwargs["start"] = int(start_time.timestamp())
        if end_time:
            api_kwargs["end"] = int(end_time.timestamp())
        
        response = self.connection.execute_with_retry(
            f"Get WAN edge stats for {device_id}",
            mistapi.api.v1.sites.stats.getSiteDeviceStats,  # type: ignore[union-attr]
            self.connection.session,
            **api_kwargs
        )
        
        return response.data if hasattr(response, 'data') else {}
    
    def get_wan_edge_events(
        self,
        site_id: str,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get WAN edge device events (status changes, flaps).
        
        Args:
            site_id: Mist site UUID
            device_id: WAN edge device UUID
            start_time: Optional start time for events window
            end_time: Optional end time for events window
            event_types: Optional list of event types to filter
        
        Returns:
            List of event dictionaries
        """
        logger.debug(f"Retrieving events for WAN edge {device_id}")
        
        events: List[Dict[str, Any]] = []
        page = 1
        
        api_kwargs: Dict[str, Union[str, int]] = {
            "site_id": site_id,
            "device_type": "gateway",
            "limit": self.connection.ops_config.page_limit,
            "page": page
        }
        
        if start_time:
            api_kwargs["start"] = int(start_time.timestamp())
        if end_time:
            api_kwargs["end"] = int(end_time.timestamp())
        
        while True:
            api_kwargs["page"] = page
            
            response = self.connection.execute_with_retry(
                f"Get WAN edge events for {device_id} (page {page})",
                mistapi.api.v1.sites.devices.searchSiteDeviceEvents,  # type: ignore[union-attr]
                self.connection.session,
                **api_kwargs
            )
            
            batch = response.data.get("results", []) if hasattr(response, 'data') else []
            
            # Filter by device_id if needed
            filtered = [event for event in batch if event.get("device_id") == device_id]
            events.extend(filtered)
            
            logger.debug(f"Retrieved {len(batch)} events from page {page}")
            
            if len(batch) < self.connection.ops_config.page_limit:
                break
            page += 1
        
        return events
    
    def get_org_wan_client_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Get organization-wide WAN client statistics.
        
        Args:
            start_time: Optional start time for stats window
            end_time: Optional end time for stats window
        
        Returns:
            List of WAN client statistics
        """
        logger.info("[...] Retrieving organization WAN client stats")
        
        api_kwargs: Dict[str, Union[str, int]] = {
            "org_id": self.connection.config.org_id
        }
        
        if start_time:
            api_kwargs["start"] = int(start_time.timestamp())
        if end_time:
            api_kwargs["end"] = int(end_time.timestamp())
        
        response = self.connection.execute_with_retry(
            "Get org WAN client stats",
            mistapi.api.v1.orgs.stats.searchOrgWanClientStats,  # type: ignore[union-attr]
            self.connection.session,
            **api_kwargs
        )
        
        results = response.data.get("results", []) if hasattr(response, 'data') else []
        logger.info(f"[OK] Retrieved {len(results)} WAN client stats records")
        return results


class MistInsightsOperations:
    """
    Handles SLE (Service Level Experience) and Alarms operations.
    
    Responsibilities:
    - Get org-level SLE metrics for all sites
    - Get worst sites by SLE metric
    - Search org-level alarms
    """
    
    def __init__(self, connection: MistConnection):
        """
        Initialize insights operations.
        
        Args:
            connection: MistConnection instance for API access
        """
        self.connection = connection
    
    def get_org_sites_sle(
        self,
        sle: str = "wan",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1d",
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Get SLE scores for all sites in the organization.
        
        Args:
            sle: SLE type - "wan", "wifi", or "wired"
            start_time: Start epoch timestamp (optional)
            end_time: End epoch timestamp (optional)
            duration: Time duration if start/end not specified ("1h", "1d", "7d")
            limit: Max results per page (default 1000)
        
        Returns:
            Dictionary with SLE data:
            {
                "start": epoch,
                "end": epoch,
                "total": count,
                "results": [
                    {
                        "site_id": "uuid",
                        "gateway-health": 0.0-1.0,
                        "wan-link-health": 0.0-1.0,
                        "application-health": 0.0-1.0,
                        "gateway-bandwidth": 0.0-1.0,
                        "num_gateways": int,
                        "num_clients": int
                    }
                ]
            }
        """
        logger.info(f"[...] Retrieving org SLE scores (sle={sle}, duration={duration})")
        
        all_results: List[Dict[str, Any]] = []
        page = 1
        total_count = 0
        response_metadata: Dict[str, Any] = {}
        
        while True:
            api_kwargs: Dict[str, Any] = {
                "org_id": self.connection.config.org_id,
                "sle": sle,
                "limit": limit,
                "page": page
            }
            
            if start_time:
                api_kwargs["start"] = start_time
            if end_time:
                api_kwargs["end"] = end_time
            if not start_time and not end_time:
                api_kwargs["duration"] = duration
            
            response = self.connection.execute_with_retry(
                f"Get org sites SLE (page {page})",
                mistapi.api.v1.orgs.insights.getOrgSitesSle,  # type: ignore[union-attr]
                self.connection.session,
                **api_kwargs
            )
            
            data = response.data if hasattr(response, 'data') else {}
            
            if page == 1:
                response_metadata = {
                    "start": data.get("start"),
                    "end": data.get("end"),
                    "total": data.get("total", 0)
                }
                total_count = data.get("total", 0)
            
            batch = data.get("results", [])
            all_results.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} SLE records from page {page}")
            
            if len(batch) < limit or len(all_results) >= total_count:
                break
            page += 1
        
        response_metadata["results"] = all_results
        logger.info(f"[OK] Retrieved SLE scores for {len(all_results)} sites")
        return response_metadata
    
    def get_org_worst_sites_by_sle(
        self,
        sle: str = "gateway-health",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1d"
    ) -> Dict[str, Any]:
        """
        Get worst performing sites by SLE metric.
        
        Args:
            sle: SLE metric - "gateway-health", "wan-link-health", "application-health"
            start_time: Start epoch timestamp (optional)
            end_time: End epoch timestamp (optional)
            duration: Time duration if start/end not specified
        
        Returns:
            Dictionary with worst sites data:
            {
                "start": epoch,
                "end": epoch,
                "results": [{"site_id": "uuid", "gateway-health": 0.0}]
            }
        """
        logger.info(f"[...] Retrieving worst sites by SLE (metric={sle})")
        
        api_kwargs: Dict[str, Any] = {
            "org_id": self.connection.config.org_id,
            "metric": "worst-sites-by-sle",
            "sle": sle
        }
        
        if start_time:
            api_kwargs["start"] = str(start_time)
        if end_time:
            api_kwargs["end"] = str(end_time)
        if not start_time and not end_time:
            api_kwargs["duration"] = duration
        
        response = self.connection.execute_with_retry(
            "Get org worst sites by SLE",
            mistapi.api.v1.orgs.insights.getOrgSle,  # type: ignore[union-attr]
            self.connection.session,
            **api_kwargs
        )
        
        data = response.data if hasattr(response, 'data') else {}
        results = data.get("results", [])
        logger.info(f"[OK] Retrieved {len(results)} worst sites by {sle}")
        return data
    
    def search_org_alarms(
        self,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1d",
        alarm_type: Optional[str] = None,
        site_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Search organization alarms.
        
        Args:
            start_time: Start epoch timestamp (optional)
            end_time: End epoch timestamp (optional)
            duration: Time duration if start/end not specified
            alarm_type: Filter by alarm type (comma-separated for multiple)
                        e.g., "infra_dhcp_failure,infra_dns_failure"
            site_id: Filter by site ID (optional)
            status: Filter by status (optional)
            limit: Max results per page
        
        Returns:
            Dictionary with alarm data:
            {
                "total": count,
                "results": [
                    {
                        "id": "alarm-uuid",
                        "site_id": "site-uuid",
                        "type": "infra_dhcp_failure",
                        "severity": "critical",
                        "group": "infrastructure",
                        "timestamp": epoch,
                        "last_seen": epoch,
                        "incident_count": int
                    }
                ]
            }
        """
        logger.info(f"[...] Searching org alarms (type={alarm_type})")
        
        all_results: List[Dict[str, Any]] = []
        total_count = 0
        search_after: Optional[str] = None
        page_num = 0
        
        while True:
            page_num += 1
            api_kwargs: Dict[str, Any] = {
                "org_id": self.connection.config.org_id,
                "limit": limit
            }
            
            if start_time:
                api_kwargs["start"] = str(start_time)
            if end_time:
                api_kwargs["end"] = str(end_time)
            if not start_time and not end_time:
                api_kwargs["duration"] = duration
            if alarm_type:
                api_kwargs["type"] = alarm_type
            if site_id:
                api_kwargs["site_id"] = site_id
            if status:
                api_kwargs["status"] = status
            if search_after:
                api_kwargs["search_after"] = search_after
            
            response = self.connection.execute_with_retry(
                f"Search org alarms (page {page_num})",
                mistapi.api.v1.orgs.alarms.searchOrgAlarms,  # type: ignore[union-attr]
                self.connection.session,
                **api_kwargs
            )
            
            data = response.data if hasattr(response, 'data') else {}
            
            if page_num == 1:
                total_count = data.get("total", 0)
            
            batch = data.get("results", [])
            all_results.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} alarms from page {page_num}")
            
            # Check for next page using search_after cursor
            next_cursor = data.get("next")
            if not next_cursor or len(batch) < limit:
                break
            search_after = next_cursor
        
        result = {
            "total": total_count,
            "results": all_results
        }
        logger.info(f"[OK] Retrieved {len(all_results)} alarms (total: {total_count})")
        return result


class MistAPIClient:
    """
    Facade for Mist Cloud API operations.
    
    Maintains backward compatibility while delegating to focused sub-classes:
    - MistConnection: Session and rate limiting
    - MistSiteOperations: Site and device retrieval
    - MistStatsOperations: Statistics and events retrieval
    - MistInsightsOperations: SLE metrics and alarms
    """
    
    def __init__(self, mist_config: MistConfig, operational_config: OperationalConfig):
        """
        Initialize the Mist API client.
        
        Args:
            mist_config: Mist API configuration (token, org_id, host)
            operational_config: Operational settings (rate limits, retries)
        """
        self.connection = MistConnection(mist_config, operational_config)
        self.site_ops = MistSiteOperations(self.connection)
        self.stats_ops = MistStatsOperations(self.connection)
        self.insights_ops = MistInsightsOperations(self.connection)
        
        # Expose config for backward compatibility
        self.config = mist_config
        self.ops_config = operational_config
        
        logger.info("[INFO] Mist API client initialized")
    
    @property
    def session(self) -> Any:
        """Get the underlying API session."""
        return self.connection.session
    
    def test_connection(self) -> bool:
        """Test the API connection by retrieving organization info."""
        return self.site_ops.test_connection()
    
    def get_sites(self) -> List[Dict[str, Any]]:
        """Get all sites in the organization."""
        return self.site_ops.get_sites()
    
    def get_site_groups(self) -> Dict[str, str]:
        """Get all site groups with human-readable names."""
        return self.site_ops.get_site_groups()
    
    def get_site_wan_edges(self, site_id: str) -> List[Dict[str, Any]]:
        """Get WAN edge devices (gateways) for a specific site."""
        return self.site_ops.get_site_wan_edges(site_id)
    
    def get_gateway_inventory(self) -> Dict[str, Any]:
        """
        Get organization gateway inventory with connection status.
        
        Returns:
            Dictionary with total, connected, disconnected counts and raw data
        """
        return self.site_ops.get_gateway_inventory()
    
    def get_org_gateway_port_stats(
        self,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int, Optional[str]], None]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway port statistics (rx_bytes, tx_bytes, speed).
        
        Args:
            on_batch: Optional callback for incremental saves during fetch.
                      Signature: on_batch(batch_records, batch_number, next_cursor)
        """
        return self.stats_ops.get_org_gateway_port_stats(on_batch=on_batch)
    
    def get_org_device_stats(self) -> List[Dict[str, Any]]:
        """Get organization-wide gateway device statistics."""
        return self.stats_ops.get_org_device_stats()
    
    def get_wan_edge_stats(
        self, 
        site_id: str, 
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get WAN edge device statistics including port utilization."""
        return self.stats_ops.get_wan_edge_stats(site_id, device_id, start_time, end_time)
    
    def get_wan_edge_events(
        self,
        site_id: str,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Get WAN edge device events (status changes, flaps)."""
        return self.stats_ops.get_wan_edge_events(
            site_id, device_id, start_time, end_time, event_types
        )
    
    def get_org_wan_client_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get organization-wide WAN client statistics."""
        return self.stats_ops.get_org_wan_client_stats(start_time, end_time)
    
    # -------------------------------------------------------------------------
    # Insights Operations (SLE and Alarms)
    # -------------------------------------------------------------------------
    
    def get_org_sites_sle(
        self,
        sle: str = "wan",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1d",
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Get SLE scores for all sites in the organization.
        
        Args:
            sle: SLE type - "wan", "wifi", or "wired"
            start_time: Start epoch timestamp (optional)
            end_time: End epoch timestamp (optional)
            duration: Time duration if start/end not specified ("1h", "1d", "7d")
            limit: Max results per page (default 1000)
        
        Returns:
            Dictionary with SLE data including site scores
        """
        return self.insights_ops.get_org_sites_sle(
            sle=sle,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            limit=limit
        )
    
    def get_org_worst_sites_by_sle(
        self,
        sle: str = "gateway-health",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1d"
    ) -> Dict[str, Any]:
        """
        Get worst performing sites by SLE metric.
        
        Args:
            sle: SLE metric - "gateway-health", "wan-link-health", "application-health"
            start_time: Start epoch timestamp (optional)
            end_time: End epoch timestamp (optional)
            duration: Time duration if start/end not specified
        
        Returns:
            Dictionary with worst sites data
        """
        return self.insights_ops.get_org_worst_sites_by_sle(
            sle=sle,
            start_time=start_time,
            end_time=end_time,
            duration=duration
        )
    
    def search_org_alarms(
        self,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        duration: str = "1d",
        alarm_type: Optional[str] = None,
        site_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000
    ) -> Dict[str, Any]:
        """
        Search organization alarms.
        
        Args:
            start_time: Start epoch timestamp (optional)
            end_time: End epoch timestamp (optional)
            duration: Time duration if start/end not specified
            alarm_type: Filter by type (e.g., "infra_dhcp_failure,infra_dns_failure")
            site_id: Filter by site ID (optional)
            status: Filter by status (optional)
            limit: Max results per page
        
        Returns:
            Dictionary with alarm data
        """
        return self.insights_ops.search_org_alarms(
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            alarm_type=alarm_type,
            site_id=site_id,
            status=status,
            limit=limit
        )
    
    def close(self) -> None:
        """Close the API session and clean up resources."""
        self.connection.close()
