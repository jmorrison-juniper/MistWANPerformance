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
        
        # Status tracking for UI display
        self.cache_status: Dict[str, Any] = {
            "fresh_sites": 0,
            "stale_sites": 0,
            "missing_sites": 0,
            "total_records": 0,
            "last_update": None
        }
        self.refresh_activity: Dict[str, Any] = {
            "active": False,
            "current_sites": [],
            "current_interfaces": [],
            "last_refresh_time": None,
            "status": "initializing"  # initializing, loading, running, idle
        }
        self.background_worker: Optional[Any] = None  # Set externally
        self.data_load_complete: bool = False  # Tracks if initial load finished
        self.failover_records: List[FailoverEventRecord] = []
        self.daily_aggregates: List[AggregatedMetrics] = []
        
        # WAN port status counts (set externally after port processing)
        self.wan_down_count: int = 0
        self.wan_disabled_count: int = 0
        
        # Gateway health counts (set externally from inventory API)
        self.gateways_connected: int = 0
        self.gateways_disconnected: int = 0
        self.gateways_total: int = 0
        self.region_aggregates: List[AggregatedMetrics] = []
        
        # SLE (Service Level Experience) data
        self.sle_data: Optional[Dict[str, Any]] = None
        self.worst_sites_gateway_health: Optional[Dict[str, Any]] = None
        self.worst_sites_wan_link: Optional[Dict[str, Any]] = None
        
        # Alarms data
        self.alarms_data: Optional[Dict[str, Any]] = None
        self.alarms_by_severity: Dict[str, int] = {}
        self.alarms_by_type: Dict[str, int] = {}
        
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
    
    def update_sle_data(self, sle_data: Dict[str, Any]):
        """
        Update SLE data cache.
        
        Args:
            sle_data: Response from get_org_sites_sle() API call
        """
        self.sle_data = sle_data
        logger.debug(f"Updated SLE data for {sle_data.get('total', 0)} sites")
    
    def update_worst_sites(
        self,
        gateway_health: Optional[Dict[str, Any]] = None,
        wan_link: Optional[Dict[str, Any]] = None
    ):
        """
        Update worst sites by SLE metric.
        
        Args:
            gateway_health: Worst sites by gateway-health
            wan_link: Worst sites by wan-link-health
        """
        if gateway_health:
            self.worst_sites_gateway_health = gateway_health
            logger.debug(f"Updated {len(gateway_health.get('results', []))} worst gateway-health sites")
        if wan_link:
            self.worst_sites_wan_link = wan_link
            logger.debug(f"Updated {len(wan_link.get('results', []))} worst wan-link sites")
    
    def update_alarms(self, alarms_data: Dict[str, Any]):
        """
        Update alarms data cache and compute summary stats.
        
        Args:
            alarms_data: Response from search_org_alarms() API call
        """
        self.alarms_data = alarms_data
        
        # Compute severity counts
        self.alarms_by_severity = {}
        self.alarms_by_type = {}
        
        for alarm in alarms_data.get("results", []):
            severity = alarm.get("severity", "unknown")
            alarm_type = alarm.get("type", "unknown")
            
            self.alarms_by_severity[severity] = self.alarms_by_severity.get(severity, 0) + 1
            self.alarms_by_type[alarm_type] = self.alarms_by_type.get(alarm_type, 0) + 1
        
        total = alarms_data.get("total", len(alarms_data.get("results", [])))
        logger.debug(f"Updated {total} alarms ({len(self.alarms_by_type)} types)")
    
    def get_sle_summary(self) -> Dict[str, Any]:
        """
        Get SLE summary for dashboard display.
        
        Returns:
            Dictionary with SLE metrics summary
        """
        if not self.sle_data:
            return {"available": False}
        
        results = self.sle_data.get("results", [])
        
        # Calculate average SLE scores across all sites
        gateway_health_scores = []
        wan_link_scores = []
        app_health_scores = []
        
        for site in results:
            if "gateway-health" in site:
                gateway_health_scores.append(site["gateway-health"])
            if "wan-link-health" in site:
                wan_link_scores.append(site["wan-link-health"])
            if "application-health" in site:
                app_health_scores.append(site["application-health"])
        
        def avg(lst: List[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0
        
        def count_below_threshold(lst: List[float], threshold: float) -> int:
            return len([v for v in lst if v < threshold])
        
        return {
            "available": True,
            "total_sites": len(results),
            "gateway_health_avg": round(avg(gateway_health_scores) * 100, 1),
            "wan_link_avg": round(avg(wan_link_scores) * 100, 1),
            "app_health_avg": round(avg(app_health_scores) * 100, 1),
            "sites_gateway_degraded": count_below_threshold(gateway_health_scores, 0.9),
            "sites_wan_degraded": count_below_threshold(wan_link_scores, 0.9),
            "sites_app_degraded": count_below_threshold(app_health_scores, 0.9),
            "worst_gateway_health": self.worst_sites_gateway_health,
            "worst_wan_link": self.worst_sites_wan_link
        }
    
    def get_alarms_summary(self) -> Dict[str, Any]:
        """
        Get alarms summary for dashboard display.
        
        Returns:
            Dictionary with alarm counts and breakdown
        """
        if not self.alarms_data:
            return {"available": False, "total": 0}
        
        return {
            "available": True,
            "total": self.alarms_data.get("total", 0),
            "by_severity": self.alarms_by_severity,
            "by_type": self.alarms_by_type,
            "critical_count": self.alarms_by_severity.get("critical", 0),
            "warn_count": self.alarms_by_severity.get("warn", 0),
            "recent_alarms": self.alarms_data.get("results", [])[:10]  # Top 10 recent
        }
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """
        Get all data needed for dashboard rendering.
        
        Returns:
            Dictionary with all dashboard data structures.
            Returns loading state if no data available yet.
        """
        # Return loading state if no data yet (async loading in progress)
        if not self.utilization_records:
            return {
                "loading": True,
                "total_sites": 0,
                "healthy_sites": 0,
                "degraded_sites": 0,
                "critical_sites": 0,
                "active_failovers": 0,
                "alert_count": 0,
                "top_congested": [],
                "alerts": [],
                "utilization_dist": {},
                "region_summary": [],
                "trends": [],
                "throughput": []
            }
        
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
        
        # Get trends data (real-time utilization %)
        trends = self._calculate_trends()
        
        # Get throughput data (cumulative bytes converted to rates)
        throughput = self._calculate_throughput()
        
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
            "trends": trends,
            "throughput": throughput,
            "sle_summary": self.get_sle_summary(),
            "alarms_summary": self.get_alarms_summary()
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
        
        Uses finer granularity for low utilization (where most circuits live)
        and coarser buckets for high utilization (alert conditions).
        
        Returns:
            Dictionary with bucket counts (ordered for display)
        """
        # Get latest utilization per circuit
        circuit_latest = {}
        for record in self.utilization_records:
            key = (record.site_id, record.circuit_id)
            if key not in circuit_latest or record.hour_key > circuit_latest[key].hour_key:
                circuit_latest[key] = record
        
        # Buckets with finer granularity at low end, coarser at high end
        # Most WAN circuits operate well below 10% utilization
        buckets = {
            "0-1%": 0,
            "1-5%": 0,
            "5-10%": 0,
            "10-25%": 0,
            "25-50%": 0,
            "50-70%": 0,
            "70-90%": 0,
            "90-100%": 0
        }
        
        for record in circuit_latest.values():
            util = record.utilization_pct
            if util < 1:
                buckets["0-1%"] += 1
            elif util < 5:
                buckets["1-5%"] += 1
            elif util < 10:
                buckets["5-10%"] += 1
            elif util < 25:
                buckets["10-25%"] += 1
            elif util < 50:
                buckets["25-50%"] += 1
            elif util < 70:
                buckets["50-70%"] += 1
            elif util < 90:
                buckets["70-90%"] += 1
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
        
        First tries to load historical trends from Redis cache.
        Falls back to current snapshot data if no historical data available.
        
        Returns:
            List of trend data points for real-time utilization chart
        """
        # Try to get historical trends from Redis if cache is available
        if hasattr(self, 'redis_cache') and self.redis_cache is not None:
            try:
                trends = self.redis_cache.get_utilization_trends(hours=24)
                if trends and len(trends) > 1:
                    logger.debug(f"[TRENDS] Loaded {len(trends)} historical points from Redis")
                    return trends
            except Exception as error:
                logger.warning(f"[TRENDS] Redis trends unavailable: {error}")
        
        # Fallback: Use current snapshot grouped by hour_key
        # (only useful if we have data from multiple hours)
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
    
    def _calculate_throughput(self) -> List[Dict[str, Any]]:
        """
        Calculate cumulative throughput data for the last 24 hours.
        
        Uses historical byte counters from Redis to show actual throughput
        over time (delta between snapshots).
        
        Returns:
            List of throughput data points (rx_mbps, tx_mbps)
        """
        # Try to get throughput history from Redis
        if hasattr(self, 'redis_cache') and self.redis_cache is not None:
            try:
                throughput = self.redis_cache.get_throughput_history(hours=24)
                if throughput and len(throughput) > 1:
                    logger.debug(f"[THROUGHPUT] Loaded {len(throughput)} historical points from Redis")
                    return throughput
            except Exception as error:
                logger.warning(f"[THROUGHPUT] Redis throughput unavailable: {error}")
        
        # Fallback: Return current snapshot totals as single point
        total_rx = sum(r.rx_bytes for r in self.utilization_records)
        total_tx = sum(r.tx_bytes for r in self.utilization_records)
        
        return [{
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M"),
            "datetime": datetime.now(timezone.utc).isoformat(),
            "rx_mbps": 0,  # Can't calculate rate from single snapshot
            "tx_mbps": 0,
            "total_rx_gb": round(total_rx / (1024 ** 3), 2),
            "total_tx_gb": round(total_tx / (1024 ** 3), 2)
        }]
    
    def store_snapshot_for_trends(self) -> bool:
        """
        Store current utilization snapshot for trends history.
        
        Should be called after each data refresh to build up historical data.
        
        Returns:
            True if snapshot was stored successfully
        """
        if not hasattr(self, 'redis_cache') or self.redis_cache is None:
            return False
        
        if not self.utilization_records:
            return False
        
        try:
            # Calculate summary metrics
            utils = [r.utilization_pct for r in self.utilization_records]
            total_rx = sum(r.rx_bytes for r in self.utilization_records)
            total_tx = sum(r.tx_bytes for r in self.utilization_records)
            
            avg_util = sum(utils) / len(utils) if utils else 0
            max_util = max(utils) if utils else 0
            circuit_count = len(set((r.site_id, r.circuit_id) for r in self.utilization_records))
            
            # Store snapshot
            success = self.redis_cache.store_utilization_snapshot(
                avg_utilization=avg_util,
                max_utilization=max_util,
                circuit_count=circuit_count,
                total_rx_bytes=total_rx,
                total_tx_bytes=total_tx
            )
            
            if success:
                logger.debug(f"[TRENDS] Stored snapshot: avg={avg_util:.1f}%, max={max_util:.1f}%, circuits={circuit_count}")
            
            return success
        except Exception as error:
            logger.error(f"[TRENDS] Failed to store snapshot: {error}")
            return False

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
    
    def get_circuit_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics for WAN circuits.
        
        Returns:
            Dictionary with circuit counts and utilization summaries
        """
        if not self.utilization_records:
            return {
                "total_circuits": 0,
                "circuits_up": 0,
                "circuits_down": self.wan_down_count,
                "circuits_disabled": self.wan_disabled_count,
                "avg_utilization": 0.0,
                "max_utilization": 0.0,
                "circuits_above_70": 0,
                "circuits_above_80": 0,
                "circuits_above_90": 0,
                "primary_circuits": 0,
                "secondary_circuits": 0,
                "total_bandwidth_gbps": 0.0
            }
        
        # Get unique circuits from records
        circuit_ids = set(r.circuit_id for r in self.utilization_records)
        
        # Calculate per-circuit max utilization
        circuit_max_util: Dict[str, float] = {}
        circuit_bandwidth: Dict[str, int] = {}
        for record in self.utilization_records:
            circuit_max_util[record.circuit_id] = max(
                circuit_max_util.get(record.circuit_id, 0.0),
                record.utilization_pct
            )
            circuit_bandwidth[record.circuit_id] = record.bandwidth_mbps
        
        # Count circuits in status thresholds
        above_70 = sum(1 for util in circuit_max_util.values() if util >= 70)
        above_80 = sum(1 for util in circuit_max_util.values() if util >= 80)
        above_90 = sum(1 for util in circuit_max_util.values() if util >= 90)
        
        # Circuit status from status records (most recent)
        circuits_down = len(set(
            r.circuit_id for r in self.status_records if r.status_code == 0
        ))
        
        # Count by role from circuit dimension
        primary_count = sum(1 for c in self.circuits if c.role == "primary")
        secondary_count = sum(1 for c in self.circuits if c.role in ("secondary", "backup"))
        
        # Total bandwidth
        total_bandwidth_mbps = sum(circuit_bandwidth.values())
        
        return {
            "total_circuits": len(circuit_ids),
            "circuits_up": len(circuit_ids),
            "circuits_down": self.wan_down_count,
            "circuits_disabled": self.wan_disabled_count,
            "avg_utilization": sum(circuit_max_util.values()) / len(circuit_max_util) if circuit_max_util else 0.0,
            "max_utilization": max(circuit_max_util.values()) if circuit_max_util else 0.0,
            "circuits_above_70": above_70,
            "circuits_above_80": above_80,
            "circuits_above_90": above_90,
            "primary_circuits": primary_count,
            "secondary_circuits": secondary_count,
            "total_bandwidth_gbps": total_bandwidth_mbps / 1000.0
        }

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

    def get_gateway_health_summary(self) -> Dict[str, Any]:
        """
        Get gateway device health summary.
        
        Returns:
            Dictionary with gateway health counts:
            {
                "total": int,
                "connected": int (online/healthy),
                "disconnected": int (offline)
            }
        """
        return {
            "total": self.gateways_total,
            "connected": self.gateways_connected,
            "disconnected": self.gateways_disconnected
        }