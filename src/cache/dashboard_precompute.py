"""
Dashboard Pre-computation Service

Pre-computes all dashboard metrics in a background thread and stores them
in Redis. The dashboard then simply reads pre-computed data instead of
doing heavy computations on each browser request.

This reduces browser load and provides consistent sub-second response times.
"""

import json
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Redis key prefix for pre-computed dashboard data
DASHBOARD_PREFIX = "dashboard:"


class DashboardPrecomputer:
    """
    Pre-computes dashboard metrics and stores in Redis.
    
    Runs in a background thread, updating every 15-30 seconds.
    The Dash app reads pre-computed data for instant display.
    """
    
    def __init__(
        self,
        cache,
        data_provider,
        refresh_interval: int = 20
    ):
        """
        Initialize the pre-computer.
        
        Args:
            cache: Redis cache instance
            data_provider: DashboardDataProvider instance
            refresh_interval: Seconds between pre-compute cycles (default: 20)
        """
        self.cache = cache
        self.data_provider = data_provider
        self.refresh_interval = refresh_interval
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._precompute_cycles = 0
        self._last_precompute_time: Optional[float] = None
        self._last_duration_ms: float = 0
    
    def start(self) -> None:
        """Start the background pre-computation thread."""
        if self._running:
            logger.warning("[WARN] Precomputer already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._precompute_loop,
            name="DashboardPrecomputer",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[OK] Dashboard precomputer started "
            f"(interval: {self.refresh_interval}s)"
        )
    
    def stop(self) -> None:
        """Stop the background pre-computation thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[OK] Dashboard precomputer stopped")
    
    def _precompute_loop(self) -> None:
        """Main pre-computation loop - runs continuously without delays."""
        while self._running:
            try:
                self._run_precompute_cycle()
                # No delay - stay busy, immediately start next cycle
                
            except Exception as error:
                logger.error(
                    f"[ERROR] Precompute cycle failed: {error}",
                    exc_info=True
                )
                # Brief yield to prevent CPU spin on repeated errors
                time.sleep(0.1)
    
    def _run_precompute_cycle(self) -> None:
        """Execute one pre-computation cycle."""
        cycle_start = time.time()
        
        try:
            # Pre-compute all dashboard data
            dashboard_data = self._precompute_dashboard_data()
            
            # Pre-compute circuit summary
            circuit_summary = self._precompute_circuit_summary()
            
            # Pre-compute gateway health
            gateway_health = self._precompute_gateway_health()
            
            # Pre-compute VPN summary
            vpn_summary = self._precompute_vpn_summary()
            
            # Pre-compute status bar data
            status_bar = self._precompute_status_bar()
            
            # Store all in Redis with timestamp
            timestamp = datetime.now(timezone.utc).isoformat()
            
            self._store_precomputed(
                "main",
                {**dashboard_data, "precomputed_at": timestamp}
            )
            self._store_precomputed(
                "circuit_summary",
                {**circuit_summary, "precomputed_at": timestamp}
            )
            self._store_precomputed(
                "gateway_health",
                {**gateway_health, "precomputed_at": timestamp}
            )
            self._store_precomputed(
                "vpn_summary",
                {**vpn_summary, "precomputed_at": timestamp}
            )
            self._store_precomputed(
                "status_bar",
                {**status_bar, "precomputed_at": timestamp}
            )
            
            # Update stats
            self._precompute_cycles += 1
            self._last_precompute_time = time.time()
            self._last_duration_ms = (time.time() - cycle_start) * 1000
            
            if self._precompute_cycles <= 3 or self._precompute_cycles % 20 == 0:
                logger.info(
                    f"[OK] Precompute cycle {self._precompute_cycles}: "
                    f"{self._last_duration_ms:.0f}ms"
                )
                
        except Exception as error:
            logger.error(f"[ERROR] Precompute failed: {error}", exc_info=True)
    
    def _precompute_dashboard_data(self) -> Dict[str, Any]:
        """Pre-compute main dashboard data."""
        records = self.data_provider.utilization_records
        
        if not records:
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
                "throughput": [],
                "sle_summary": {"available": False},
                "alarms_summary": {"available": False, "total": 0},
                "sle_degraded_sites": []
            }
        
        # Calculate site statuses (heavy computation)
        site_statuses = self._compute_site_statuses()
        
        # Top congested circuits
        top_congested = self._compute_top_congested(10)
        
        # Active alerts
        alerts = self._compute_active_alerts()
        
        # Utilization distribution
        util_dist = self._compute_utilization_distribution()
        
        # Region summary
        region_summary = self._compute_region_summary()
        
        # Trends and throughput
        trends = self._compute_trends()
        throughput = self._compute_throughput()
        
        # Active failovers
        failover_records = getattr(self.data_provider, 'failover_records', [])
        active_failovers = len([
            r for r in failover_records
            if getattr(r, 'on_failover', False)
        ])
        
        # SLE data
        sle_summary = self.data_provider.get_sle_summary()
        alarms_summary = self.data_provider.get_alarms_summary()
        sle_degraded = self.data_provider.get_sle_degraded_sites()
        
        return {
            "loading": False,
            "total_sites": len(set(r.site_id for r in records)),
            "healthy_sites": site_statuses.get("healthy", 0),
            "degraded_sites": site_statuses.get("degraded", 0),
            "critical_sites": site_statuses.get("critical", 0),
            "active_failovers": active_failovers,
            "alert_count": len(alerts),
            "top_congested": top_congested,
            "alerts": alerts,
            "utilization_dist": util_dist,
            "region_summary": region_summary,
            "trends": trends,
            "throughput": throughput,
            "sle_summary": sle_summary,
            "alarms_summary": alarms_summary,
            "sle_degraded_sites": sle_degraded
        }
    
    def _compute_site_statuses(self) -> Dict[str, int]:
        """Compute site health status counts."""
        records = self.data_provider.utilization_records
        status_records = getattr(self.data_provider, 'status_records', [])
        
        site_max_util = defaultdict(float)
        site_down_circuits = defaultdict(int)
        
        # Max utilization per site
        for record in records:
            site_max_util[record.site_id] = max(
                site_max_util[record.site_id],
                record.utilization_pct
            )
        
        # Down circuits per site
        for record in status_records:
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
    
    def _compute_top_congested(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        Compute top N congested circuits.
        
        Returns data matching RankedCircuit.to_dict() format for table display:
        rank, site_id, site_name, port_id, bandwidth_mbps, metric_value, threshold_status
        """
        # Utilization thresholds
        UTIL_CRITICAL = 90.0
        UTIL_HIGH = 80.0
        UTIL_WARNING = 70.0
        
        def get_threshold_status(util_pct: float) -> str:
            """Determine threshold status for utilization."""
            if util_pct >= UTIL_CRITICAL:
                return "critical"
            elif util_pct >= UTIL_HIGH:
                return "high"
            elif util_pct >= UTIL_WARNING:
                return "warning"
            return "normal"
        
        records = self.data_provider.utilization_records
        
        # Sort by utilization descending
        sorted_records = sorted(
            records,
            key=lambda r: r.utilization_pct,
            reverse=True
        )[:top_n]
        
        result = []
        for rank, record in enumerate(sorted_records, 1):
            result.append({
                "rank": rank,
                "site_id": record.site_id,
                "site_name": self.data_provider.site_lookup.get(
                    record.site_id, record.site_id[:8]
                ),
                "port_id": record.circuit_id,
                "bandwidth_mbps": getattr(record, 'bandwidth_mbps', 0),
                "metric_value": round(record.utilization_pct, 2),
                "threshold_status": get_threshold_status(record.utilization_pct)
            })
        
        return result
    
    def _compute_active_alerts(self) -> List[Dict[str, Any]]:
        """Compute active alerts."""
        alerts = []
        records = self.data_provider.utilization_records
        status_records = getattr(self.data_provider, 'status_records', [])
        
        # High utilization alerts
        for record in records:
            if record.utilization_pct >= 90:
                alerts.append({
                    "type": "critical_utilization",
                    "severity": "critical",
                    "site_id": record.site_id,
                    "site_name": self.data_provider.site_lookup.get(
                        record.site_id, record.site_id[:8]
                    ),
                    "message": f"Utilization at {record.utilization_pct:.1f}%"
                })
            elif record.utilization_pct >= 80:
                alerts.append({
                    "type": "high_utilization",
                    "severity": "warning",
                    "site_id": record.site_id,
                    "site_name": self.data_provider.site_lookup.get(
                        record.site_id, record.site_id[:8]
                    ),
                    "message": f"Utilization at {record.utilization_pct:.1f}%"
                })
        
        # Circuit down alerts
        for record in status_records:
            if record.status_code == 0:
                alerts.append({
                    "type": "circuit_down",
                    "severity": "critical",
                    "site_id": record.site_id,
                    "site_name": self.data_provider.site_lookup.get(
                        record.site_id, record.site_id[:8]
                    ),
                    "message": "Circuit DOWN"
                })
        
        return alerts[:50]  # Limit to 50 alerts
    
    def _compute_utilization_distribution(self) -> Dict[str, int]:
        """Compute utilization distribution buckets."""
        records = self.data_provider.utilization_records
        
        dist = {
            "0-25": 0,
            "25-50": 0,
            "50-70": 0,
            "70-80": 0,
            "80-90": 0,
            "90-100": 0
        }
        
        for record in records:
            util = record.utilization_pct
            if util < 25:
                dist["0-25"] += 1
            elif util < 50:
                dist["25-50"] += 1
            elif util < 70:
                dist["50-70"] += 1
            elif util < 80:
                dist["70-80"] += 1
            elif util < 90:
                dist["80-90"] += 1
            else:
                dist["90-100"] += 1
        
        return dist
    
    def _compute_region_summary(self) -> List[Dict[str, Any]]:
        """Compute region-level summary."""
        records = self.data_provider.utilization_records
        
        region_stats = defaultdict(lambda: {
            "total": 0,
            "sum_util": 0.0,
            "max_util": 0.0,
            "critical": 0
        })
        
        for record in records:
            # Extract region from site name (first 2 chars usually state code)
            site_name = self.data_provider.site_lookup.get(
                record.site_id, "XX"
            )
            region = site_name[:2] if len(site_name) >= 2 else "XX"
            
            region_stats[region]["total"] += 1
            region_stats[region]["sum_util"] += record.utilization_pct
            region_stats[region]["max_util"] = max(
                region_stats[region]["max_util"],
                record.utilization_pct
            )
            if record.utilization_pct >= 90:
                region_stats[region]["critical"] += 1
        
        result = []
        for region, stats in sorted(region_stats.items()):
            avg_util = stats["sum_util"] / stats["total"] if stats["total"] > 0 else 0
            result.append({
                "region": region,
                "circuit_count": stats["total"],
                "avg_utilization": round(avg_util, 1),
                "max_utilization": round(stats["max_util"], 1),
                "critical_count": stats["critical"]
            })
        
        return result[:20]  # Limit to top 20 regions
    
    def _compute_trends(self) -> List[Dict[str, Any]]:
        """Compute utilization trends data."""
        # Use cached trends if available from data_provider
        if hasattr(self.data_provider, '_calculate_trends'):
            return self.data_provider._calculate_trends()
        return []
    
    def _compute_throughput(self) -> List[Dict[str, Any]]:
        """Compute throughput data."""
        # Use cached throughput if available from data_provider
        if hasattr(self.data_provider, '_calculate_throughput'):
            return self.data_provider._calculate_throughput()
        return []
    
    def _precompute_circuit_summary(self) -> Dict[str, Any]:
        """Pre-compute circuit summary metrics."""
        records = self.data_provider.utilization_records
        status_records = getattr(self.data_provider, 'status_records', [])
        
        if not records:
            return {
                "circuits_up": 0,
                "circuits_down": 0,
                "circuits_disabled": 0,
                "circuits_above_80": 0,
                "avg_utilization": 0.0,
                "max_utilization": 0.0,
                "total_bandwidth_gbps": 0.0
            }
        
        circuits_up = len(records)
        circuits_down = len([r for r in status_records if r.status_code == 0])
        circuits_disabled = len([
            r for r in records
            if getattr(r, 'role', '') == 'disabled'
        ])
        circuits_above_80 = len([r for r in records if r.utilization_pct >= 80])
        
        total_util = sum(r.utilization_pct for r in records)
        avg_util = total_util / len(records) if records else 0
        max_util = max(r.utilization_pct for r in records) if records else 0
        
        total_bw = sum(getattr(r, 'bandwidth_mbps', 0) for r in records)
        total_bw_gbps = total_bw / 1000
        
        return {
            "circuits_up": circuits_up,
            "circuits_down": circuits_down,
            "circuits_disabled": circuits_disabled,
            "circuits_above_80": circuits_above_80,
            "avg_utilization": round(avg_util, 1),
            "max_utilization": round(max_util, 1),
            "total_bandwidth_gbps": round(total_bw_gbps, 1)
        }
    
    def _precompute_gateway_health(self) -> Dict[str, Any]:
        """Pre-compute gateway health summary."""
        return self.data_provider.get_gateway_health_summary()
    
    def _precompute_vpn_summary(self) -> Dict[str, Any]:
        """Pre-compute VPN peer summary."""
        return self.data_provider.get_vpn_peer_summary()
    
    def _precompute_status_bar(self) -> Dict[str, Any]:
        """Pre-compute status bar data."""
        from src.api.mist_client import get_rate_limit_status
        
        rate_status = get_rate_limit_status()
        
        # Cache status
        cache_status = {"fresh": 0, "stale": 0, "missing": 0}
        if hasattr(self.cache, 'get_cache_stats'):
            try:
                cache_status = self.cache.get_cache_stats()
            except Exception:
                pass
        
        # Worker statuses
        worker_statuses = {}
        
        if hasattr(self.data_provider, 'sle_background_worker'):
            worker = self.data_provider.sle_background_worker
            if worker:
                worker_statuses["sle"] = worker.get_status()
        
        if hasattr(self.data_provider, 'background_worker'):
            worker = self.data_provider.background_worker
            if worker:
                worker_statuses["ports"] = worker.get_status()
        
        if hasattr(self.data_provider, 'vpn_background_worker'):
            worker = self.data_provider.vpn_background_worker
            if worker:
                worker_statuses["vpn"] = worker.get_status()
        
        return {
            "rate_limited": rate_status.get("rate_limited", False),
            "rate_status": rate_status,
            "cache_status": cache_status,
            "worker_statuses": worker_statuses
        }
    
    def _store_precomputed(self, key: str, data: Dict[str, Any]) -> None:
        """Store pre-computed data in Redis."""
        full_key = f"{DASHBOARD_PREFIX}{key}"
        
        try:
            # Check for Redis client (attribute is 'client', not 'redis')
            if hasattr(self.cache, 'client') and self.cache.client:
                self.cache.client.set(
                    full_key,
                    json.dumps(data),
                    ex=2678400  # 31 days minimum TTL
                )
            elif hasattr(self.cache, '_precomputed'):
                # Fallback for NullCache
                self.cache._precomputed[key] = data
        except Exception as error:
            logger.warning(f"[WARN] Failed to store precomputed {key}: {error}")
    
    def get_precomputed(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get pre-computed data from Redis.
        
        Args:
            key: Data key (without prefix)
            
        Returns:
            Pre-computed data dict or None if not available
        """
        full_key = f"{DASHBOARD_PREFIX}{key}"
        
        try:
            # Check for Redis client (attribute is 'client', not 'redis')
            if hasattr(self.cache, 'client') and self.cache.client:
                data = self.cache.client.get(full_key)
                if data:
                    return json.loads(data)
            elif hasattr(self.cache, '_precomputed'):
                return self.cache._precomputed.get(key)
        except Exception as error:
            logger.warning(f"[WARN] Failed to get precomputed {key}: {error}")
        
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get precomputer status for monitoring."""
        return {
            "running": self._running,
            "precompute_cycles": self._precompute_cycles,
            "last_precompute_time": self._last_precompute_time,
            "last_duration_ms": self._last_duration_ms,
            "refresh_interval": self.refresh_interval
        }
