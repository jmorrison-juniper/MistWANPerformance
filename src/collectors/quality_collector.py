"""
MistWANPerformance - Quality Collector

Collects circuit quality metrics (loss, jitter, latency) from Mist WAN edge devices.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import statistics

from src.api.mist_client import MistAPIClient
from src.models.facts import CircuitQualityRecord


logger = logging.getLogger(__name__)


class QualityCollector:
    """
    Collector for WAN circuit quality metrics.
    
    Metrics collected:
    - frame_loss_pct: Packet/frame loss percentage
    - jitter_ms: Network jitter in milliseconds
    - latency_ms: Network latency in milliseconds
    - Statistical aggregates: avg, max, p95 for each metric
    """
    
    def __init__(self, api_client: MistAPIClient):
        """
        Initialize the quality collector.
        
        Args:
            api_client: Initialized Mist API client
        """
        self.api_client = api_client
        logger.debug("QualityCollector initialized")
    
    def collect_for_site(
        self,
        site_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitQualityRecord]:
        """
        Collect quality metrics for all circuits at a site.
        
        Args:
            site_id: Mist site UUID
            start_time: Start of collection window (default: last hour)
            end_time: End of collection window (default: now)
        
        Returns:
            List of CircuitQualityRecord objects
        """
        logger.info(f"[...] Collecting quality metrics for site {site_id}")
        
        # Default time window: last hour
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        if start_time is None:
            start_time = end_time - timedelta(hours=1)
        
        records = []
        
        # Get WAN edge devices for site
        wan_edges = self.api_client.get_site_wan_edges(site_id)
        logger.debug(f"Found {len(wan_edges)} WAN edge devices")
        
        for device in wan_edges:
            device_id = device.get("id")
            if not device_id:
                continue
            
            device_records = self._collect_device_quality(
                site_id, device_id, device, start_time, end_time
            )
            records.extend(device_records)
        
        logger.info(f"[OK] Collected {len(records)} quality records for site {site_id}")
        return records
    
    def _collect_device_quality(
        self,
        site_id: str,
        device_id: str,
        device: Dict[str, Any],
        start_time: datetime,
        end_time: datetime
    ) -> List[CircuitQualityRecord]:
        """
        Collect quality metrics for a specific WAN edge device.
        
        Args:
            site_id: Mist site UUID
            device_id: Device UUID
            device: Device info dictionary
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            List of CircuitQualityRecord objects
        """
        records = []
        
        # Get device stats
        stats = self.api_client.get_wan_edge_stats(site_id, device_id, start_time, end_time)
        
        # Look for WAN interface quality metrics
        port_stats = stats.get("port_stats", {})
        wan_interfaces = stats.get("wan_interfaces", [])
        
        # Process WAN interfaces for quality data
        for wan_if in wan_interfaces:
            record = self._create_quality_record_from_wan_interface(
                site_id, device_id, wan_if, start_time, end_time
            )
            if record:
                records.append(record)
        
        # Also check port stats for quality data
        for port_name, port_data in port_stats.items():
            # Skip if we already have WAN interface data for this port
            if any(r.circuit_id.endswith(port_name) for r in records):
                continue
            
            record = self._create_quality_record_from_port(
                site_id, device_id, port_name, port_data, start_time, end_time
            )
            if record:
                records.append(record)
        
        return records
    
    def _create_quality_record_from_wan_interface(
        self,
        site_id: str,
        device_id: str,
        wan_if: Dict[str, Any],
        start_time: datetime,
        end_time: datetime
    ) -> Optional[CircuitQualityRecord]:
        """
        Create quality record from WAN interface data.
        
        Args:
            site_id: Mist site UUID
            device_id: Device UUID
            wan_if: WAN interface statistics
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            CircuitQualityRecord or None
        """
        try:
            interface_name = wan_if.get("name", "unknown")
            
            # Extract quality metrics
            # Note: Actual field names depend on Mist API response structure
            loss_samples = wan_if.get("loss_samples", [])
            jitter_samples = wan_if.get("jitter_samples", [])
            latency_samples = wan_if.get("latency_samples", [])
            
            # If no samples, try single values
            if not loss_samples:
                loss_val = wan_if.get("loss_pct") or wan_if.get("loss")
                loss_samples = [loss_val] if loss_val is not None else []
            
            if not jitter_samples:
                jitter_val = wan_if.get("jitter_ms") or wan_if.get("jitter")
                jitter_samples = [jitter_val] if jitter_val is not None else []
            
            if not latency_samples:
                latency_val = wan_if.get("latency_ms") or wan_if.get("latency")
                latency_samples = [latency_val] if latency_val is not None else []
            
            # Calculate statistics
            loss_stats = self._calculate_statistics(loss_samples)
            jitter_stats = self._calculate_statistics(jitter_samples)
            latency_stats = self._calculate_statistics(latency_samples)
            
            # Generate hour_key
            hour_key = end_time.strftime("%Y%m%d%H")
            
            return CircuitQualityRecord(
                site_id=site_id,
                circuit_id=f"{device_id}:{interface_name}",
                hour_key=hour_key,
                frame_loss_pct=loss_stats.get("avg"),
                loss_avg=loss_stats.get("avg"),
                loss_max=loss_stats.get("max"),
                loss_p95=loss_stats.get("p95"),
                jitter_ms=jitter_stats.get("avg"),
                jitter_avg=jitter_stats.get("avg"),
                jitter_max=jitter_stats.get("max"),
                jitter_p95=jitter_stats.get("p95"),
                latency_ms=latency_stats.get("avg"),
                latency_avg=latency_stats.get("avg"),
                latency_max=latency_stats.get("max"),
                latency_p95=latency_stats.get("p95"),
                collected_at=datetime.now(timezone.utc)
            )
            
        except Exception as error:
            logger.warning(
                f"[WARN] Failed to create quality record from WAN interface: {error}"
            )
            return None
    
    def _create_quality_record_from_port(
        self,
        site_id: str,
        device_id: str,
        port_name: str,
        port_data: Dict[str, Any],
        start_time: datetime,
        end_time: datetime
    ) -> Optional[CircuitQualityRecord]:
        """
        Create quality record from port statistics.
        
        Args:
            site_id: Mist site UUID
            device_id: Device UUID
            port_name: Port name
            port_data: Port statistics dictionary
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            CircuitQualityRecord or None
        """
        try:
            # Extract error counts for loss calculation
            rx_errors = port_data.get("rx_errors", 0)
            rx_pkts = port_data.get("rx_pkts", 0)
            
            # Calculate frame loss percentage
            frame_loss_pct = None
            if rx_pkts > 0:
                frame_loss_pct = (rx_errors / rx_pkts) * 100
            
            # Port stats typically don't include jitter/latency
            # Those come from SLA monitoring or WAN interface stats
            
            if frame_loss_pct is None:
                return None  # No quality data available
            
            # Generate hour_key
            hour_key = end_time.strftime("%Y%m%d%H")
            
            return CircuitQualityRecord(
                site_id=site_id,
                circuit_id=f"{device_id}:{port_name}",
                hour_key=hour_key,
                frame_loss_pct=round(frame_loss_pct, 4),
                loss_avg=round(frame_loss_pct, 4),
                loss_max=round(frame_loss_pct, 4),
                loss_p95=round(frame_loss_pct, 4),
                jitter_ms=None,
                jitter_avg=None,
                jitter_max=None,
                jitter_p95=None,
                latency_ms=None,
                latency_avg=None,
                latency_max=None,
                latency_p95=None,
                collected_at=datetime.now(timezone.utc)
            )
            
        except Exception as error:
            logger.warning(
                f"[WARN] Failed to create quality record from port {port_name}: {error}"
            )
            return None
    
    def _calculate_statistics(
        self,
        samples: List[float]
    ) -> Dict[str, Optional[float]]:
        """
        Calculate statistical aggregates from samples.
        
        Args:
            samples: List of metric values
        
        Returns:
            Dictionary with avg, max, p95 values
        """
        # Filter out None values
        valid_samples = [s for s in samples if s is not None]
        
        if not valid_samples:
            return {"avg": None, "max": None, "p95": None}
        
        avg_val = round(statistics.mean(valid_samples), 4)
        max_val = round(max(valid_samples), 4)
        
        # Calculate p95
        if len(valid_samples) >= 20:
            # Need enough samples for meaningful percentile
            sorted_samples = sorted(valid_samples)
            p95_index = int(len(sorted_samples) * 0.95)
            p95_val = round(sorted_samples[p95_index], 4)
        else:
            # Not enough samples, use max as p95 approximation
            p95_val = max_val
        
        return {"avg": avg_val, "max": max_val, "p95": p95_val}
    
    def collect_for_org(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[CircuitQualityRecord]:
        """
        Collect quality metrics for all sites in the organization.
        
        Args:
            start_time: Start of collection window
            end_time: End of collection window
        
        Returns:
            List of CircuitQualityRecord objects for all sites
        """
        logger.info("[...] Collecting quality metrics for organization")
        
        all_records = []
        sites = self.api_client.get_sites()
        
        for site in sites:
            site_id = site.get("id")
            if not site_id:
                continue
            
            site_records = self.collect_for_site(site_id, start_time, end_time)
            all_records.extend(site_records)
        
        logger.info(f"[OK] Collected {len(all_records)} total quality records")
        return all_records
