"""
MistWANPerformance - Ranking Views

Query generators for top-N sites, circuits, and regions by various metrics.
Designed for NOC dashboard consumption.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from enum import Enum

from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    AggregatedMetrics,
    RollingWindowMetrics
)


logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Available metrics for ranking."""
    UTILIZATION = "utilization"
    AVAILABILITY = "availability"
    FLAPS = "flaps"
    LOSS = "loss"
    JITTER = "jitter"
    LATENCY = "latency"


class SortOrder(Enum):
    """Sort direction for rankings."""
    ASCENDING = "asc"
    DESCENDING = "desc"


@dataclass
class RankedCircuit:
    """
    A circuit with its ranking information.
    
    Used for top-N and worst-N displays.
    """
    rank: int
    site_id: str
    site_name: Optional[str]
    port_id: str
    bandwidth_mbps: int
    metric_value: float
    metric_name: str
    threshold_status: str  # "normal", "warning", "high", "critical"
    period_type: str  # "current", "hourly", "daily", etc.
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API/dashboard consumption."""
        return {
            "rank": self.rank,
            "site_id": self.site_id,
            "site_name": self.site_name,
            "port_id": self.port_id,
            "bandwidth_mbps": self.bandwidth_mbps,
            "metric_value": self.metric_value,
            "metric_name": self.metric_name,
            "threshold_status": self.threshold_status,
            "period_type": self.period_type
        }


class RankingViews:
    """
    Query generators for ranking views.
    
    Provides:
    - Top N circuits by utilization
    - Worst N circuits by availability
    - Chronic offenders (repeated threshold breaches)
    - Region rankings
    """
    
    # Default thresholds for status classification
    UTIL_THRESHOLDS = {"warning": 70.0, "high": 80.0, "critical": 90.0}
    AVAIL_THRESHOLDS = {"critical": 99.0, "high": 99.5, "warning": 99.9}
    
    def __init__(
        self,
        site_lookup: Optional[Dict[str, str]] = None,
        region_lookup: Optional[Dict[str, str]] = None
    ):
        """
        Initialize the ranking views.
        
        Args:
            site_lookup: Mapping of site_id to site_name
            region_lookup: Mapping of site_id to region
        """
        self.site_lookup = site_lookup or {}
        self.region_lookup = region_lookup or {}
        logger.debug("RankingViews initialized")
    
    def _get_threshold_status(
        self,
        value: float,
        metric_type: MetricType
    ) -> str:
        """
        Determine threshold status for a metric value.
        
        Args:
            value: Metric value
            metric_type: Type of metric
        
        Returns:
            Status string: "normal", "warning", "high", or "critical"
        """
        if metric_type == MetricType.UTILIZATION:
            if value >= self.UTIL_THRESHOLDS["critical"]:
                return "critical"
            elif value >= self.UTIL_THRESHOLDS["high"]:
                return "high"
            elif value >= self.UTIL_THRESHOLDS["warning"]:
                return "warning"
        elif metric_type == MetricType.AVAILABILITY:
            # Lower is worse for availability
            if value < self.AVAIL_THRESHOLDS["critical"]:
                return "critical"
            elif value < self.AVAIL_THRESHOLDS["high"]:
                return "high"
            elif value < self.AVAIL_THRESHOLDS["warning"]:
                return "warning"
        
        return "normal"
    
    def top_n_by_utilization(
        self,
        utilization_records: List[CircuitUtilizationRecord],
        top_n: int = 10,
        period_type: str = "hourly"
    ) -> List[RankedCircuit]:
        """
        Get top N circuits by utilization (highest first).
        
        Args:
            utilization_records: List of utilization records
            top_n: Number of results to return
            period_type: Period label for display
        
        Returns:
            List of RankedCircuit objects, sorted by utilization descending
        """
        if not utilization_records:
            return []
        
        # Group by circuit and get max utilization with bandwidth
        circuit_data = {}
        for record in utilization_records:
            key = (record.site_id, record.circuit_id)
            if key not in circuit_data:
                circuit_data[key] = {
                    "utilization_pct": record.utilization_pct,
                    "bandwidth_mbps": record.bandwidth_mbps
                }
            else:
                if record.utilization_pct > circuit_data[key]["utilization_pct"]:
                    circuit_data[key]["utilization_pct"] = record.utilization_pct
                    circuit_data[key]["bandwidth_mbps"] = record.bandwidth_mbps
        
        # Sort by utilization descending
        sorted_circuits = sorted(
            circuit_data.items(),
            key=lambda x: x[1]["utilization_pct"],
            reverse=True
        )[:top_n]
        
        # Build ranked results
        results = []
        for rank, ((site_id, port_id), data) in enumerate(sorted_circuits, 1):
            results.append(RankedCircuit(
                rank=rank,
                site_id=site_id,
                site_name=self.site_lookup.get(site_id),
                port_id=port_id,
                bandwidth_mbps=data["bandwidth_mbps"],
                metric_value=round(data["utilization_pct"], 2),
                metric_name="utilization_pct",
                threshold_status=self._get_threshold_status(data["utilization_pct"], MetricType.UTILIZATION),
                period_type=period_type
            ))
        
        logger.info(f"[OK] Generated top {len(results)} by utilization")
        return results
    
    def worst_n_by_availability(
        self,
        status_records: List[CircuitStatusRecord],
        top_n: int = 10,
        period_type: str = "daily"
    ) -> List[RankedCircuit]:
        """
        Get worst N circuits by availability (lowest first).
        
        Args:
            status_records: List of status records
            top_n: Number of results to return
            period_type: Period label for display
        
        Returns:
            List of RankedCircuit objects, sorted by availability ascending
        """
        if not status_records:
            return []
        
        # Group by circuit and calculate availability
        circuit_totals = {}
        for record in status_records:
            key = (record.site_id, record.circuit_id)
            if key not in circuit_totals:
                circuit_totals[key] = {"up": 0, "down": 0}
            circuit_totals[key]["up"] += record.up_minutes
            circuit_totals[key]["down"] += record.down_minutes
        
        # Calculate availability percentage
        circuit_avail = {}
        for key, totals in circuit_totals.items():
            total = totals["up"] + totals["down"]
            if total > 0:
                circuit_avail[key] = (totals["up"] / total) * 100
        
        # Sort by availability ascending (worst first)
        sorted_circuits = sorted(
            circuit_avail.items(),
            key=lambda x: x[1]
        )[:top_n]
        
        # Build ranked results
        results = []
        for rank, ((site_id, port_id), avail_value) in enumerate(sorted_circuits, 1):
            results.append(RankedCircuit(
                rank=rank,
                site_id=site_id,
                site_name=self.site_lookup.get(site_id),
                port_id=port_id,
                bandwidth_mbps=0,  # Not available from status records
                metric_value=round(avail_value, 4),
                metric_name="availability_pct",
                threshold_status=self._get_threshold_status(avail_value, MetricType.AVAILABILITY),
                period_type=period_type
            ))
        
        logger.info(f"[OK] Generated worst {len(results)} by availability")
        return results
    
    def top_n_by_flaps(
        self,
        status_records: List[CircuitStatusRecord],
        top_n: int = 10,
        period_type: str = "daily"
    ) -> List[RankedCircuit]:
        """
        Get top N circuits by flap count (most flaps first).
        
        Args:
            status_records: List of status records
            top_n: Number of results to return
            period_type: Period label for display
        
        Returns:
            List of RankedCircuit objects, sorted by flaps descending
        """
        if not status_records:
            return []
        
        # Group by circuit and sum flaps
        circuit_flaps = {}
        for record in status_records:
            key = (record.site_id, record.circuit_id)
            if key not in circuit_flaps:
                circuit_flaps[key] = 0
            circuit_flaps[key] += record.flap_count
        
        # Sort by flaps descending
        sorted_circuits = sorted(
            circuit_flaps.items(),
            key=lambda x: x[1],
            reverse=True
        )[:top_n]
        
        # Build ranked results
        results = []
        for rank, ((site_id, port_id), flap_count) in enumerate(sorted_circuits, 1):
            # Flaps threshold status
            if flap_count >= 10:
                status = "critical"
            elif flap_count >= 5:
                status = "high"
            elif flap_count >= 2:
                status = "warning"
            else:
                status = "normal"
            
            results.append(RankedCircuit(
                rank=rank,
                site_id=site_id,
                site_name=self.site_lookup.get(site_id),
                port_id=port_id,
                bandwidth_mbps=0,  # Not available from status records
                metric_value=float(flap_count),
                metric_name="flap_count",
                threshold_status=status,
                period_type=period_type
            ))
        
        logger.info(f"[OK] Generated top {len(results)} by flaps")
        return results
    
    def chronic_offenders(
        self,
        aggregates: List[AggregatedMetrics],
        threshold_pct: float = 80.0,
        min_breaches: int = 3
    ) -> List[RankedCircuit]:
        """
        Find circuits that repeatedly breach thresholds.
        
        A chronic offender has exceeded the threshold for min_breaches
        or more periods within the aggregation window.
        
        Args:
            aggregates: Daily or weekly aggregates
            threshold_pct: Utilization threshold to check
            min_breaches: Minimum breach count to be flagged
        
        Returns:
            List of RankedCircuit objects for chronic offenders
        """
        if not aggregates:
            return []
        
        # Count periods above threshold per circuit
        circuit_breaches = {}
        for agg in aggregates:
            key = (agg.site_id, agg.circuit_id)
            if key not in circuit_breaches:
                circuit_breaches[key] = {"count": 0, "max": 0.0}
            
            util_max = agg.utilization_max or 0.0
            if util_max >= threshold_pct:
                circuit_breaches[key]["count"] += 1
                circuit_breaches[key]["max"] = max(circuit_breaches[key]["max"], util_max)
        
        # Filter to chronic offenders
        offenders = [
            (key, data) for key, data in circuit_breaches.items()
            if data["count"] >= min_breaches
        ]
        
        # Sort by breach count descending
        sorted_offenders = sorted(
            offenders,
            key=lambda x: x[1]["count"],
            reverse=True
        )
        
        # Build ranked results
        results = []
        for rank, ((site_id, port_id), data) in enumerate(sorted_offenders, 1):
            results.append(RankedCircuit(
                rank=rank,
                site_id=site_id,
                site_name=self.site_lookup.get(site_id),
                port_id=port_id,
                bandwidth_mbps=0,  # Not tracked for chronic offenders
                metric_value=float(data["count"]),
                metric_name=f"breach_count_above_{threshold_pct}",
                threshold_status="critical" if data["count"] >= 5 else "high",
                period_type="chronic"
            ))
        
        logger.info(f"[OK] Found {len(results)} chronic offenders")
        return results
    
    def region_rankings(
        self,
        aggregates: List[AggregatedMetrics],
        metric_type: MetricType = MetricType.UTILIZATION
    ) -> List[Dict[str, Any]]:
        """
        Rank regions by aggregate metrics.
        
        Args:
            aggregates: Region-level aggregates (circuit_id=None)
            metric_type: Metric to rank by
        
        Returns:
            List of region ranking dictionaries
        """
        # Filter to region-level aggregates
        region_aggs = [a for a in aggregates if a.circuit_id is None]
        
        if not region_aggs:
            return []
        
        # Get metric value based on type
        def get_metric(agg: AggregatedMetrics) -> float:
            if metric_type == MetricType.UTILIZATION:
                return agg.utilization_avg or 0.0
            elif metric_type == MetricType.AVAILABILITY:
                return agg.availability_pct or 100.0
            elif metric_type == MetricType.FLAPS:
                return float(agg.total_flaps)
            else:
                return 0.0
        
        # Sort appropriately
        reverse = metric_type != MetricType.AVAILABILITY
        sorted_regions = sorted(
            region_aggs,
            key=get_metric,
            reverse=reverse
        )
        
        results = []
        for rank, agg in enumerate(sorted_regions, 1):
            results.append({
                "rank": rank,
                "region": agg.site_id,  # Region stored in site_id for region-level
                "metric_value": round(get_metric(agg), 2),
                "metric_name": metric_type.value,
                "period_key": agg.period_key,
                "period_type": agg.period_type
            })
        
        logger.info(f"[OK] Generated {len(results)} region rankings by {metric_type.value}")
        return results
