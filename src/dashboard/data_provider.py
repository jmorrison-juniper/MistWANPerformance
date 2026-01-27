"""
MistWANPerformance - Dashboard Data Provider

Provides data to the dashboard from collectors and aggregators.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from collections import defaultdict

from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    FailoverEventRecord,
    AggregatedMetrics
)
from src.models.dimensions import DimSite, DimCircuit
from src.views.rankings import RankingViews
from src.views.current_state import CurrentStateViews


logger = logging.getLogger(__name__)


class DashboardDataProvider:
    """
    Data provider for the WAN Performance Dashboard.
    
    Aggregates data from collectors and provides formatted
    data structures for dashboard consumption.
    """
    
    def __init__(
        self,
        sites: Optional[List[DimSite]] = None,
        circuits: Optional[List[DimCircuit]] = None
    ):
        """
        Initialize the data provider.
        
        Args:
            sites: List of site dimension records
            circuits: List of circuit dimension records
        """
        self.sites = sites or []
        self.circuits = circuits or []
        
        # Build lookup dictionaries
        self.site_lookup: Dict[str, str] = {
            s.site_id: s.site_name for s in self.sites
        }
        self.region_lookup: Dict[str, str] = {
            s.site_id: (s.region or "Unknown") for s in self.sites
        }
        self.circuit_role_lookup: Dict[str, str] = {
            c.circuit_id: c.role for c in self.circuits
        }
        
        # Initialize view generators
        self.ranking_views = RankingViews(self.site_lookup, self.region_lookup)
        self.current_state_views = CurrentStateViews(
            self.site_lookup, self.region_lookup, self.circuit_role_lookup
        )
        
        # Data stores (in-memory cache)
        self.utilization_records: List[CircuitUtilizationRecord] = []
        self.status_records: List[CircuitStatusRecord] = []
        self.quality_records: List[CircuitQualityRecord] = []
        self.failover_records: List[FailoverEventRecord] = []
        self.daily_aggregates: List[AggregatedMetrics] = []
        self.region_aggregates: List[AggregatedMetrics] = []
        
        logger.debug("DashboardDataProvider initialized")
    
    def update_utilization(self, records: List[CircuitUtilizationRecord]):
        """Update utilization records cache."""
        self.utilization_records = records
        logger.debug(f"Updated {len(records)} utilization records")
    
    def update_status(self, records: List[CircuitStatusRecord]):
        """Update status records cache."""
        self.status_records = records
        logger.debug(f"Updated {len(records)} status records")
    
    def update_quality(self, records: List[CircuitQualityRecord]):
        """Update quality records cache."""
        self.quality_records = records
        logger.debug(f"Updated {len(records)} quality records")
    
    def update_failovers(self, records: List[FailoverEventRecord]):
        """Update failover records cache."""
        self.failover_records = records
        logger.debug(f"Updated {len(records)} failover records")
    
    def update_aggregates(
        self,
        daily: List[AggregatedMetrics],
        region: List[AggregatedMetrics]
    ):
        """Update aggregate caches."""
        self.daily_aggregates = daily
        self.region_aggregates = region
        logger.debug(f"Updated {len(daily)} daily, {len(region)} region aggregates")
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get all data needed for dashboard rendering.
        
        Returns:
            Dictionary with all dashboard data structures
        """
        # Calculate site status counts
        site_statuses = self._calculate_site_statuses()
        
        # Get top congested circuits
        top_congested = self.ranking_views.top_n_by_utilization(
            self.utilization_records, top_n=10
        )
        
        # Get current alerts
        circuit_states = self._get_all_circuit_states()
        alerts = self.current_state_views.get_active_alerts(circuit_states)
        
        # Get utilization distribution
        util_dist = self._calculate_utilization_distribution()
        
        # Get region summary
        region_summary = self._calculate_region_summary()
        
        # Get trends data
        trends = self._calculate_trends()
        
        # Get active failovers
        active_failovers = self.current_state_views.get_failover_status(
            self.failover_records
        )
        
        return {
            "total_sites": len(set(r.site_id for r in self.utilization_records)),
            "healthy_sites": site_statuses.get("healthy", 0),
            "degraded_sites": site_statuses.get("degraded", 0),
            "critical_sites": site_statuses.get("critical", 0),
            "active_failovers": len(active_failovers),
            "alert_count": len(alerts),
            "top_congested": [c.to_dict() for c in top_congested],
            "alerts": alerts,
            "utilization_dist": util_dist,
            "region_summary": region_summary,
            "trends": trends
        }
    
    def _calculate_site_statuses(self) -> Dict[str, int]:
        """
        Calculate site health status counts.
        
        Returns:
            Dictionary with healthy/degraded/critical counts
        """
        site_max_util = defaultdict(float)
        site_down_circuits = defaultdict(int)
        
        # Get max utilization per site
        for record in self.utilization_records:
            site_max_util[record.site_id] = max(
                site_max_util[record.site_id],
                record.utilization_pct
            )
        
        # Count down circuits per site
        for record in self.status_records:
            if record.status_code == 0:
                site_down_circuits[record.site_id] += 1
        
        # Classify sites
        all_sites = set(site_max_util.keys()) | set(site_down_circuits.keys())
        
        statuses = {"healthy": 0, "degraded": 0, "critical": 0}
        
        for site_id in all_sites:
            max_util = site_max_util.get(site_id, 0)
            down_count = site_down_circuits.get(site_id, 0)
            
            if down_count > 0 or max_util >= 90:
                statuses["critical"] += 1
            elif max_util >= 70:
                statuses["degraded"] += 1
            else:
                statuses["healthy"] += 1
        
        return statuses
    
    def _get_all_circuit_states(self) -> List:
        """
        Get current state for all circuits.
        
        Returns:
            List of CircuitCurrentState objects
        """
        # Group records by circuit
        util_by_circuit = defaultdict(list)
        status_by_circuit = defaultdict(list)
        quality_by_circuit = defaultdict(list)
        
        for record in self.utilization_records:
            key = (record.site_id, record.circuit_id)
            util_by_circuit[key].append(record)
        
        for record in self.status_records:
            key = (record.site_id, record.circuit_id)
            status_by_circuit[key].append(record)
        
        for record in self.quality_records:
            key = (record.site_id, record.circuit_id)
            quality_by_circuit[key].append(record)
        
        # Generate states
        all_circuits = set(util_by_circuit.keys()) | set(status_by_circuit.keys())
        
        states = []
        for site_id, circuit_id in all_circuits:
            state = self.current_state_views.get_circuit_current_state(
                site_id=site_id,
                circuit_id=circuit_id,
                utilization_records=sorted(
                    util_by_circuit[(site_id, circuit_id)],
                    key=lambda r: r.hour_key
                ),
                status_records=sorted(
                    status_by_circuit[(site_id, circuit_id)],
                    key=lambda r: r.hour_key
                ),
                quality_records=sorted(
                    quality_by_circuit[(site_id, circuit_id)],
                    key=lambda r: r.hour_key
                ),
                failover_records=self.failover_records
            )
            states.append(state)
        
        return states
    
    def _calculate_utilization_distribution(self) -> Dict[str, int]:
        """
        Calculate distribution of circuits across utilization buckets.
        
        Returns:
            Dictionary with bucket counts
        """
        # Get latest utilization per circuit
        circuit_latest = {}
        for record in self.utilization_records:
            key = (record.site_id, record.circuit_id)
            if key not in circuit_latest or record.hour_key > circuit_latest[key].hour_key:
                circuit_latest[key] = record
        
        # Bucket the values
        buckets = {
            "0-50%": 0,
            "50-70%": 0,
            "70-80%": 0,
            "80-90%": 0,
            "90-100%": 0
        }
        
        for record in circuit_latest.values():
            util = record.utilization_pct
            if util < 50:
                buckets["0-50%"] += 1
            elif util < 70:
                buckets["50-70%"] += 1
            elif util < 80:
                buckets["70-80%"] += 1
            elif util < 90:
                buckets["80-90%"] += 1
            else:
                buckets["90-100%"] += 1
        
        return buckets
    
    def _calculate_region_summary(self) -> List[Dict[str, Any]]:
        """
        Calculate summary statistics by region.
        
        Returns:
            List of region summary dictionaries
        """
        region_utilizations: Dict[str, List[float]] = defaultdict(list)
        region_counts: Dict[str, int] = defaultdict(int)
        
        for record in self.utilization_records:
            region = self.region_lookup.get(record.site_id, "Unknown")
            region_utilizations[region].append(record.utilization_pct)
            region_counts[region] += 1
        
        summaries = []
        for region in region_utilizations:
            util_list = region_utilizations[region]
            if util_list:
                avg_util = sum(util_list) / len(util_list)
            else:
                avg_util = 0.0
            
            summaries.append({
                "region": region,
                "avg_utilization": round(avg_util, 1),
                "circuit_count": region_counts[region]
            })
        
        return sorted(summaries, key=lambda x: x["avg_utilization"], reverse=True)
    
    def _calculate_trends(self) -> List[Dict[str, Any]]:
        """
        Calculate trend data for the last 24 hours.
        
        Returns:
            List of trend data points
        """
        # Group by hour
        hour_data = defaultdict(list)
        
        for record in self.utilization_records:
            hour_key = record.hour_key
            hour_data[hour_key].append(record.utilization_pct)
        
        # Calculate stats per hour
        trends = []
        for hour_key in sorted(hour_data.keys())[-24:]:
            values = hour_data[hour_key]
            trends.append({
                "timestamp": f"{hour_key[8:10]}:00",
                "avg_utilization": round(sum(values) / len(values), 1) if values else 0,
                "max_utilization": round(max(values), 1) if values else 0
            })
        
        return trends    
    def get_region_sites(self, region: str) -> List[Dict[str, Any]]:
        """
        Get all sites in a region for drilldown view.
        
        Args:
            region: Region name
        
        Returns:
            List of site dictionaries with metrics
        """
        # Find sites in this region
        sites_in_region = [
            s for s in self.sites
            if (s.region or "Unknown") == region
        ]
        
        site_data = []
        for site in sites_in_region:
            site_id = site.site_id
            
            # Get latest metrics for this site
            site_utils = [r for r in self.utilization_records if r.site_id == site_id]
            site_status = [r for r in self.status_records if r.site_id == site_id]
            
            circuit_count = len(set(r.circuit_id for r in site_utils))
            avg_util = sum(r.utilization_pct for r in site_utils) / len(site_utils) if site_utils else 0
            
            # Determine status
            down_count = sum(1 for r in site_status if r.status_code == 0)
            status = "healthy"
            if down_count > 0:
                status = "critical"
            elif avg_util >= 80:
                status = "critical"
            elif avg_util >= 70:
                status = "degraded"
            
            site_data.append({
                "site_id": site_id,
                "site_name": site.site_name,
                "circuit_count": circuit_count,
                "avg_utilization": round(avg_util, 1),
                "status": status
            })
        
        return sorted(site_data, key=lambda x: x["avg_utilization"], reverse=True)
    
    def get_site_circuits(self, site_id: str) -> List[Dict[str, Any]]:
        """
        Get all circuits for a site for drilldown view.
        
        Args:
            site_id: Site UUID
        
        Returns:
            List of circuit dictionaries with metrics
        """
        # Get circuits for this site
        site_circuits = [c for c in self.circuits if c.site_id == site_id]
        
        circuit_data = []
        for circuit in site_circuits:
            circuit_id = circuit.circuit_id
            
            # Get latest metrics
            util_records = [r for r in self.utilization_records if r.circuit_id == circuit_id]
            status_records = [r for r in self.status_records if r.circuit_id == circuit_id]
            quality_records = [r for r in self.quality_records if r.circuit_id == circuit_id]
            
            latest_util = max(util_records, key=lambda r: r.hour_key) if util_records else None
            latest_status = max(status_records, key=lambda r: r.hour_key) if status_records else None
            latest_quality = max(quality_records, key=lambda r: r.hour_key) if quality_records else None
            
            # Calculate availability
            total_up = sum(r.up_minutes for r in status_records)
            total_down = sum(r.down_minutes for r in status_records)
            availability = (total_up / (total_up + total_down) * 100) if (total_up + total_down) > 0 else 100
            
            circuit_data.append({
                "circuit_id": circuit_id,
                "role": circuit.role,
                "status": "Up" if latest_status and latest_status.status_code == 1 else "Down",
                "utilization_pct": round(latest_util.utilization_pct, 1) if latest_util else None,
                "availability_pct": round(availability, 2),
                "latency_ms": round(latest_quality.latency_avg, 1) if latest_quality and latest_quality.latency_avg else None,
                "is_active": circuit.active_state
            })
        
        return circuit_data
    
    def get_circuit_timeseries(self, circuit_id: str) -> List[Dict[str, Any]]:
        """
        Get time series data for a circuit for drilldown view.
        
        Args:
            circuit_id: Circuit identifier
        
        Returns:
            List of time series data points
        """
        util_records = sorted(
            [r for r in self.utilization_records if r.circuit_id == circuit_id],
            key=lambda r: r.hour_key
        )
        status_records = sorted(
            [r for r in self.status_records if r.circuit_id == circuit_id],
            key=lambda r: r.hour_key
        )
        quality_records = sorted(
            [r for r in self.quality_records if r.circuit_id == circuit_id],
            key=lambda r: r.hour_key
        )
        
        # Build time series
        time_series = []
        all_hours = sorted(set(
            [r.hour_key for r in util_records] +
            [r.hour_key for r in status_records] +
            [r.hour_key for r in quality_records]
        ))
        
        util_by_hour = {r.hour_key: r for r in util_records}
        status_by_hour = {r.hour_key: r for r in status_records}
        quality_by_hour = {r.hour_key: r for r in quality_records}
        
        for hour_key in all_hours[-24:]:  # Last 24 hours
            util = util_by_hour.get(hour_key)
            status = status_by_hour.get(hour_key)
            quality = quality_by_hour.get(hour_key)
            
            time_series.append({
                "timestamp": f"{hour_key[:4]}-{hour_key[4:6]}-{hour_key[6:8]} {hour_key[8:10]}:00",
                "utilization_pct": util.utilization_pct if util else None,
                "availability_pct": status.availability_pct if status else 100,
                "latency_ms": quality.latency_avg if quality else None,
                "jitter_ms": quality.jitter_avg if quality else None,
                "loss_pct": quality.loss_avg if quality else None
            })
        
        return time_series
    
    def get_primary_secondary_comparison(self, site_id: str) -> Dict[str, Any]:
        """
        Get primary vs secondary comparison data for a site.
        
        Args:
            site_id: Site UUID
        
        Returns:
            Comparison dictionary
        """
        # Find primary and secondary circuits for this site
        site_circuits = [c for c in self.circuits if c.site_id == site_id]
        primary = next((c for c in site_circuits if c.role == "primary"), None)
        secondary = next((c for c in site_circuits if c.role in ("secondary", "backup")), None)
        
        if not primary and not secondary:
            return {"error": "No circuits found for site"}
        
        # Get records for each circuit
        primary_util = [r for r in self.utilization_records if primary and r.circuit_id == primary.circuit_id]
        secondary_util = [r for r in self.utilization_records if secondary and r.circuit_id == secondary.circuit_id]
        primary_quality = [r for r in self.quality_records if primary and r.circuit_id == primary.circuit_id]
        secondary_quality = [r for r in self.quality_records if secondary and r.circuit_id == secondary.circuit_id]
        primary_status = [r for r in self.status_records if primary and r.circuit_id == primary.circuit_id]
        secondary_status = [r for r in self.status_records if secondary and r.circuit_id == secondary.circuit_id]
        
        return self.current_state_views.get_primary_vs_secondary_comparison(
            site_id=site_id,
            primary_utilization=sorted(primary_util, key=lambda r: r.hour_key),
            secondary_utilization=sorted(secondary_util, key=lambda r: r.hour_key),
            primary_quality=sorted(primary_quality, key=lambda r: r.hour_key),
            secondary_quality=sorted(secondary_quality, key=lambda r: r.hour_key),
            primary_status=sorted(primary_status, key=lambda r: r.hour_key),
            secondary_status=sorted(secondary_status, key=lambda r: r.hour_key),
            failover_records=self.failover_records
        )