"""
MistWANPerformance - Status Collector

Collects circuit status and flap events from Mist WAN edge devices.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.api.mist_client import MistAPIClient
from src.models.facts import CircuitStatusRecord


logger = logging.getLogger(__name__)


@dataclass
class StatusRecordInput:
    """
    Input data container for creating status records.
    
    Groups related parameters to comply with 5-parameter limit.
    """
    site_id: str
    device_id: str
    port_name: str
    port_data: Dict[str, Any]
    events: List[Dict[str, Any]]


@dataclass
class TimeWindow:
    """
    Time window for data collection.
    
    Groups start and end time parameters.
    """
    start_time: datetime
    end_time: datetime


class StatusCollector:
    """
    Collector for WAN circuit status and flap metrics.
    
    Metrics collected:
    - status_code: Current status (up/down)
    - up_minutes: Minutes circuit was up in the hour
    - down_minutes: Minutes circuit was down in the hour
    - flap_count: Count of status transitions
    """
    
    # Status event types to monitor
    STATUS_EVENT_TYPES = ["GW_PORT_UP", "GW_PORT_DOWN", "GW_WAN_UP", "GW_WAN_DOWN"]
    
    def __init__(self, api_client: MistAPIClient):
        """
        Initialize the status collector.
        
        Args:
            api_client: Initialized Mist API client
        """
        self.api_client = api_client
        logger.debug("StatusCollector initialized")
    
    def collect_for_site(
        self,
        site_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitStatusRecord]:
        """
        Collect status metrics for all circuits at a site.
        
        Args:
            site_id: Mist site UUID
            start_time: Start of collection window (default: last hour)
            end_time: End of collection window (default: now)
        
        Returns:
            List of CircuitStatusRecord objects
        """
        logger.info(f"[...] Collecting status for site {site_id}")
        
        # Default time window: last hour
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(hours=1)
        
        time_window = TimeWindow(start_time=start_time, end_time=end_time)
        records = []
        
        # Get WAN edge devices for site
        wan_edges = self.api_client.get_site_wan_edges(site_id)
        logger.debug(f"Found {len(wan_edges)} WAN edge devices")
        
        for device in wan_edges:
            device_id = device.get("id")
            if not device_id:
                continue
            
            device_records = self._collect_device_status(site_id, device_id, device, time_window)
            records.extend(device_records)
        
        logger.info(f"[OK] Collected {len(records)} status records for site {site_id}")
        return records
    
    def _collect_device_status(
        self,
        site_id: str,
        device_id: str,
        device: Dict[str, Any],
        time_window: TimeWindow
    ) -> List[CircuitStatusRecord]:
        """
        Collect status metrics for a specific WAN edge device.
        
        Args:
            site_id: Mist site UUID
            device_id: Device UUID
            device: Device info dictionary
            time_window: Collection time window
        
        Returns:
            List of CircuitStatusRecord objects
        """
        records = []
        
        # Get events for this device
        events = self.api_client.get_wan_edge_events(
            site_id, device_id, time_window.start_time, 
            time_window.end_time, self.STATUS_EVENT_TYPES
        )
        
        # Get device stats for current port status
        stats = self.api_client.get_wan_edge_stats(
            site_id, device_id, time_window.start_time, time_window.end_time
        )
        port_stats = stats.get("port_stats", {})
        
        # Process each port
        for port_name, port_data in port_stats.items():
            port_events = self._filter_events_for_port(events, port_name)
            
            record_input = StatusRecordInput(
                site_id=site_id,
                device_id=device_id,
                port_name=port_name,
                port_data=port_data,
                events=port_events
            )
            
            record = self._create_status_record(record_input, time_window)
            if record:
                records.append(record)
        
        return records
    
    def _filter_events_for_port(
        self, 
        events: List[Dict[str, Any]], 
        port_name: str
    ) -> List[Dict[str, Any]]:
        """
        Filter events relevant to a specific port.
        
        Args:
            events: List of all device events
            port_name: Port name to filter for
        
        Returns:
            Filtered list of events
        """
        # Filter events that mention this port
        filtered = []
        for event in events:
            event_port = event.get("port_id", "") or event.get("port", "")
            if port_name.lower() in event_port.lower():
                filtered.append(event)
        return filtered
    
    def _calculate_uptime_minutes(
        self,
        events: List[Dict[str, Any]],
        current_status: str,
        time_window: TimeWindow
    ) -> Tuple[int, int, int]:
        """
        Calculate up/down minutes and flap count from events.
        
        Args:
            events: List of status change events
            current_status: Current port status
            time_window: Calculation time window
        
        Returns:
            Tuple of (up_minutes, down_minutes, flap_count)
        """
        total_minutes = int(
            (time_window.end_time - time_window.start_time).total_seconds() / 60
        )
        
        if not events:
            # No events means status was constant
            if current_status == "up":
                return (total_minutes, 0, 0)
            else:
                return (0, total_minutes, 0)
        
        return self._calculate_from_events(events, current_status, time_window)
    
    def _calculate_from_events(
        self,
        events: List[Dict[str, Any]],
        current_status: str,
        time_window: TimeWindow
    ) -> Tuple[int, int, int]:
        """
        Calculate uptime from sorted events.
        
        Args:
            events: List of status change events
            current_status: Current port status
            time_window: Calculation time window
        
        Returns:
            Tuple of (up_minutes, down_minutes, flap_count)
        """
        # Sort events by timestamp
        sorted_events = sorted(events, key=lambda event: event.get("timestamp", 0))
        
        up_seconds = 0
        down_seconds = 0
        flap_count = 0
        last_timestamp = time_window.start_time.timestamp()
        last_status = "unknown"
        
        for event in sorted_events:
            event_ts = event.get("timestamp", 0)
            event_type = event.get("type", "")
            
            # Determine status change
            if "UP" in event_type:
                new_status = "up"
            elif "DOWN" in event_type:
                new_status = "down"
            else:
                continue
            
            # Calculate time spent in previous state
            duration = event_ts - last_timestamp
            if last_status == "up":
                up_seconds += duration
            elif last_status == "down":
                down_seconds += duration
            
            # Count flap if status changed
            if last_status != "unknown" and last_status != new_status:
                flap_count += 1
            
            last_timestamp = event_ts
            last_status = new_status
        
        # Account for time from last event to end of window
        remaining = time_window.end_time.timestamp() - last_timestamp
        if last_status == "up" or (last_status == "unknown" and current_status == "up"):
            up_seconds += remaining
        else:
            down_seconds += remaining
        
        up_minutes = int(up_seconds / 60)
        down_minutes = int(down_seconds / 60)
        
        return (up_minutes, down_minutes, flap_count)
    
    def _create_status_record(
        self,
        record_input: StatusRecordInput,
        time_window: TimeWindow
    ) -> Optional[CircuitStatusRecord]:
        """
        Create a CircuitStatusRecord from input data.
        
        Args:
            record_input: Container with port data and events
            time_window: Collection time window
        
        Returns:
            CircuitStatusRecord or None if data is invalid
        """
        try:
            current_status = "up" if record_input.port_data.get("up", False) else "down"
            status_code = 1 if current_status == "up" else 0
            
            up_minutes, down_minutes, flap_count = self._calculate_uptime_minutes(
                record_input.events, current_status, time_window
            )
            
            # Generate hour_key
            hour_key = time_window.end_time.strftime("%Y%m%d%H")
            
            return CircuitStatusRecord(
                site_id=record_input.site_id,
                circuit_id=f"{record_input.device_id}:{record_input.port_name}",
                hour_key=hour_key,
                status_code=status_code,
                up_minutes=up_minutes,
                down_minutes=down_minutes,
                flap_count=flap_count,
                collected_at=datetime.now(timezone.utc)
            )
            
        except Exception as error:
            logger.warning(
                f"[WARN] Failed to create status record for {record_input.port_name}: {error}"
            )
            return None
    
    def collect_for_org(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitStatusRecord]:
        """
        Collect status metrics for all sites in the organization.
        
        Args:
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            List of CircuitStatusRecord objects for all sites
        """
        logger.info("[...] Collecting status for organization")
        
        all_records = []
        sites = self.api_client.get_sites()
        
        for site in sites:
            site_id = site.get("id")
            if not site_id:
                continue
            
            site_records = self.collect_for_site(site_id, start_time, end_time)
            all_records.extend(site_records)
        
        logger.info(f"[OK] Collected {len(all_records)} total status records")
        return all_records
