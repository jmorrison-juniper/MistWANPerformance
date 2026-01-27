"""
MistWANPerformance - Utilization Collector

Collects circuit utilization metrics from Mist WAN edge devices.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.api.mist_client import MistAPIClient
from src.models.facts import CircuitUtilizationRecord


logger = logging.getLogger(__name__)


class UtilizationCollector:
    """
    Collector for WAN circuit utilization metrics.
    
    Metrics collected:
    - rx_bytes: Received bytes
    - tx_bytes: Transmitted bytes  
    - utilization_pct: Calculated utilization percentage
    """
    
    def __init__(self, api_client: MistAPIClient):
        """
        Initialize the utilization collector.
        
        Args:
            api_client: Initialized Mist API client
        """
        self.api_client = api_client
        logger.debug("UtilizationCollector initialized")
    
    def collect_for_site(
        self,
        site_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitUtilizationRecord]:
        """
        Collect utilization metrics for all circuits at a site.
        
        Args:
            site_id: Mist site UUID
            start_time: Start of collection window (default: last hour)
            end_time: End of collection window (default: now)
        
        Returns:
            List of CircuitUtilizationRecord objects
        """
        logger.info(f"[...] Collecting utilization for site {site_id}")
        
        records = []
        
        # Get WAN edge devices for site
        wan_edges = self.api_client.get_site_wan_edges(site_id)
        logger.debug(f"Found {len(wan_edges)} WAN edge devices")
        
        for device in wan_edges:
            device_id = device.get("id")
            if not device_id:
                continue
            
            device_records = self._collect_device_utilization(
                site_id, device_id, device, start_time, end_time
            )
            records.extend(device_records)
        
        logger.info(f"[OK] Collected {len(records)} utilization records for site {site_id}")
        return records
    
    def _collect_device_utilization(
        self,
        site_id: str,
        device_id: str,
        device: Dict[str, Any],
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitUtilizationRecord]:
        """
        Collect utilization metrics for a specific WAN edge device.
        
        Args:
            site_id: Mist site UUID
            device_id: Device UUID
            device: Device info dictionary
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            List of CircuitUtilizationRecord objects for device ports
        """
        records = []
        
        # Get device stats
        stats = self.api_client.get_wan_edge_stats(
            site_id, device_id, start_time, end_time
        )
        
        # Extract port statistics
        port_stats = stats.get("port_stats", {})
        
        for port_name, port_data in port_stats.items():
            record = self._create_utilization_record(
                site_id, device_id, device, port_name, port_data
            )
            if record:
                records.append(record)
        
        return records
    
    def _create_utilization_record(
        self,
        site_id: str,
        device_id: str,
        device: Dict[str, Any],
        port_name: str,
        port_data: Dict[str, Any]
    ) -> Optional[CircuitUtilizationRecord]:
        """
        Create a CircuitUtilizationRecord from port statistics.
        
        Args:
            site_id: Mist site UUID
            device_id: Device UUID
            device: Device info dictionary
            port_name: Port name (e.g., "ge-0/0/0")
            port_data: Port statistics dictionary
        
        Returns:
            CircuitUtilizationRecord or None if data is invalid
        """
        try:
            rx_bytes = port_data.get("rx_bytes", 0)
            tx_bytes = port_data.get("tx_bytes", 0)
            speed_mbps = port_data.get("speed", 1000)  # Default 1Gbps
            
            # Calculate bandwidth in bytes (speed is in Mbps)
            bandwidth_bytes = (speed_mbps * 1000000) / 8
            
            # Utilization = max(rx, tx) / bandwidth * 100
            max_bytes = max(rx_bytes, tx_bytes)
            utilization_pct = (max_bytes / bandwidth_bytes * 100) if bandwidth_bytes > 0 else 0.0
            
            # Cap at 100%
            utilization_pct = min(utilization_pct, 100.0)
            
            # Generate hour_key for current hour
            now = datetime.now(timezone.utc)
            hour_key = now.strftime("%Y%m%d%H")
            
            return CircuitUtilizationRecord(
                site_id=site_id,
                circuit_id=f"{device_id}:{port_name}",
                hour_key=hour_key,
                utilization_pct=round(utilization_pct, 2),
                rx_bytes=rx_bytes,
                tx_bytes=tx_bytes,
                bandwidth_mbps=speed_mbps,
                collected_at=now
            )
            
        except Exception as error:
            logger.warning(
                f"[WARN] Failed to create utilization record for {port_name}: {error}"
            )
            return None
    
    def collect_for_org(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitUtilizationRecord]:
        """
        Collect utilization metrics for all sites in the organization.
        
        Args:
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            List of CircuitUtilizationRecord objects for all sites
        """
        logger.info("[...] Collecting utilization for organization")
        
        all_records = []
        sites = self.api_client.get_sites()
        
        for site in sites:
            site_id = site.get("id")
            if not site_id:
                continue
            
            site_records = self.collect_for_site(site_id, start_time, end_time)
            all_records.extend(site_records)
        
        logger.info(f"[OK] Collected {len(all_records)} total utilization records")
        return all_records
