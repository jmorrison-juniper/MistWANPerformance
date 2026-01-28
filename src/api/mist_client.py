"""
MistWANPerformance - Mist API Client

This module provides a client for interacting with the Juniper Mist Cloud API,
specifically for WAN circuit performance data collection.

Split into focused classes per 5-item rule:
- MistConnection: Session management and rate limiting
- MistSiteOperations: Site and device retrieval
- MistStatsOperations: Statistics and events retrieval
- MistAPIClient: Facade maintaining backward compatibility
"""

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
        Execute an API call with retry logic.
        
        Args:
            operation: Description of the operation (for logging)
            api_call: Callable API method
            *args: Positional arguments for API call
            **kwargs: Keyword arguments for API call
        
        Returns:
            API response data
        
        Raises:
            Exception: If all retries are exhausted
        """
        last_error: Optional[Exception] = None
        
        for attempt in range(1, self.ops_config.max_retries + 1):
            try:
                self.apply_rate_limit()
                response = api_call(*args, **kwargs)
                return response
            except Exception as error:
                last_error = error
                logger.warning(
                    f"[WARN] {operation} failed (attempt {attempt}/{self.ops_config.max_retries}): {error}"
                )
                if attempt < self.ops_config.max_retries:
                    time.sleep(self.ops_config.retry_delay * attempt)
        
        logger.error(f"[ERROR] {operation} failed after {self.ops_config.max_retries} attempts")
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{operation} failed with unknown error")
    
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
    
    def get_org_gateway_port_stats(self) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway port statistics.
        
        This is the primary method for getting real WAN utilization data.
        Returns rx_bytes, tx_bytes, speed, and status for all WAN ports.
        Fetches ALL available data with no batch limits.
        
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


class MistAPIClient:
    """
    Facade for Mist Cloud API operations.
    
    Maintains backward compatibility while delegating to focused sub-classes:
    - MistConnection: Session and rate limiting
    - MistSiteOperations: Site and device retrieval
    - MistStatsOperations: Statistics and events retrieval
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
    
    def get_org_gateway_port_stats(self) -> List[Dict[str, Any]]:
        """Get organization-wide gateway port statistics (rx_bytes, tx_bytes, speed)."""
        return self.stats_ops.get_org_gateway_port_stats()
    
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
    
    def close(self) -> None:
        """Close the API session and clean up resources."""
        self.connection.close()
