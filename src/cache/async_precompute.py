"""
Async Pre-computation Workers

Parallelized precomputation using:
- asyncio + TaskGroup for I/O-bound work (Redis, network)
- ProcessPoolExecutor for CPU-bound computation

This provides significant speedup over sequential processing:
- Per-site precomputation: 50+ sites processed in parallel
- Dashboard computation: Heavy CPU work offloaded to process pool
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Redis key prefixes
DASHBOARD_PREFIX = "dashboard:"
SITE_SLE_PREFIX = "dashboard:site_sle:"
SITE_VPN_PREFIX = "dashboard:site_vpn:"

# Process pool for CPU-bound work (module-level for reuse)
_process_pool: Optional[ProcessPoolExecutor] = None


def get_process_pool() -> ProcessPoolExecutor:
    """Get or create the shared process pool."""
    global _process_pool
    if _process_pool is None:
        # Use fewer workers than CPU cores to leave room for main process
        import os
        workers = max(2, (os.cpu_count() or 4) - 2)
        _process_pool = ProcessPoolExecutor(max_workers=workers)
        logger.info(f"[OK] Process pool created with {workers} workers")
    return _process_pool


def shutdown_process_pool():
    """Shutdown the process pool."""
    global _process_pool
    if _process_pool:
        _process_pool.shutdown(wait=False)
        _process_pool = None


# ==============================================================================
# CPU-bound computation functions (run in process pool)
# ==============================================================================

def compute_site_statuses_cpu(
    utilization_data: List[Tuple[str, float]],
    status_data: List[Tuple[str, int]]
) -> Dict[str, int]:
    """
    Compute site health status counts.
    
    Runs in process pool - must be a standalone function with serializable args.
    """
    site_max_util: Dict[str, float] = {}
    site_down_circuits: Dict[str, int] = {}
    
    # Max utilization per site
    for site_id, util_pct in utilization_data:
        current = site_max_util.get(site_id, 0.0)
        site_max_util[site_id] = max(current, util_pct)
    
    # Down circuits per site
    for site_id, status_code in status_data:
        if status_code == 0:
            site_down_circuits[site_id] = site_down_circuits.get(site_id, 0) + 1
    
    # Classify sites
    healthy = 0
    degraded = 0
    critical = 0
    
    all_sites = set(site_max_util.keys())
    for site_id in all_sites:
        max_util = site_max_util.get(site_id, 0)
        down_count = site_down_circuits.get(site_id, 0)
        
        if down_count > 0 or max_util >= 90:
            critical += 1
        elif max_util >= 70:
            degraded += 1
        else:
            healthy += 1
    
    return {"healthy": healthy, "degraded": degraded, "critical": critical}


def compute_utilization_distribution_cpu(
    utilization_data: List[Tuple[str, float]]
) -> Dict[str, int]:
    """
    Compute utilization distribution buckets.
    
    Runs in process pool.
    """
    buckets = {
        "0-1%": 0, "1-5%": 0, "5-10%": 0, "10-25%": 0,
        "25-50%": 0, "50-70%": 0, "70-90%": 0, "90-100%": 0
    }
    
    for _, util_pct in utilization_data:
        if util_pct < 1:
            buckets["0-1%"] += 1
        elif util_pct < 5:
            buckets["1-5%"] += 1
        elif util_pct < 10:
            buckets["5-10%"] += 1
        elif util_pct < 25:
            buckets["10-25%"] += 1
        elif util_pct < 50:
            buckets["25-50%"] += 1
        elif util_pct < 70:
            buckets["50-70%"] += 1
        elif util_pct < 90:
            buckets["70-90%"] += 1
        else:
            buckets["90-100%"] += 1
    
    return buckets


def compute_region_summary_cpu(
    utilization_data: List[Tuple[str, str, float]]
) -> List[Dict[str, Any]]:
    """
    Compute region-level summary statistics.
    
    Args:
        utilization_data: List of (site_id, region, utilization_pct) tuples
    
    Runs in process pool.
    """
    region_stats: Dict[str, Dict[str, Any]] = {}
    
    for site_id, region, util_pct in utilization_data:
        if region not in region_stats:
            region_stats[region] = {
                "sites": set(),
                "total_util": 0.0,
                "count": 0,
                "max_util": 0.0
            }
        
        stats = region_stats[region]
        stats["sites"].add(site_id)
        stats["total_util"] += util_pct
        stats["count"] += 1
        stats["max_util"] = max(stats["max_util"], util_pct)
    
    result = []
    for region, stats in region_stats.items():
        avg_util = stats["total_util"] / stats["count"] if stats["count"] > 0 else 0
        result.append({
            "region": region,
            "site_count": len(stats["sites"]),
            "avg_utilization": round(avg_util, 2),
            "max_utilization": round(stats["max_util"], 2)
        })
    
    # Sort by site count descending
    result.sort(key=lambda x: x["site_count"], reverse=True)
    return result


def compute_top_congested_cpu(
    utilization_data: List[Tuple[str, str, str, float, int, int]],
    top_n: int = 10
) -> List[Dict[str, Any]]:
    """
    Compute top N congested circuits.
    
    Args:
        utilization_data: List of (circuit_id, site_id, site_name, util_pct, rx_bytes, tx_bytes)
        top_n: Number of top circuits to return
    
    Runs in process pool.
    """
    # Sort by utilization descending
    sorted_data = sorted(utilization_data, key=lambda x: x[3], reverse=True)
    
    result = []
    for circuit_id, site_id, site_name, util_pct, rx_bytes, tx_bytes in sorted_data[:top_n]:
        result.append({
            "circuit_id": circuit_id,
            "site_id": site_id,
            "site_name": site_name,
            "utilization_pct": round(util_pct, 2),
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes
        })
    
    return result


# ==============================================================================
# Async Dashboard Precomputer
# ==============================================================================

class AsyncDashboardPrecomputer:
    """
    Async dashboard precomputer with parallel I/O and CPU offloading.
    
    Uses:
    - asyncio.to_thread() for blocking Redis operations
    - ProcessPoolExecutor for CPU-heavy computations
    - TaskGroup for parallel data gathering
    """
    
    def __init__(
        self,
        cache,
        data_provider,
        refresh_interval: int = 20
    ):
        """
        Initialize the async precomputer.
        
        Args:
            cache: Redis cache instance
            data_provider: DashboardDataProvider instance
            refresh_interval: Seconds between pre-compute cycles
        """
        self.cache = cache
        self.data_provider = data_provider
        self.refresh_interval = refresh_interval
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._precompute_cycles = 0
        self._last_precompute_time: Optional[float] = None
        self._last_duration_ms: float = 0
    
    def start(self) -> None:
        """Start the async precomputation loop."""
        if self._running:
            logger.warning("[WARN] Async dashboard precomputer already running")
            return
        
        self._running = True
        
        # Get or create event loop
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Schedule the async task
        self._task = loop.create_task(self._precompute_loop())
        logger.info(
            f"[OK] Async dashboard precomputer started "
            f"(interval: {self.refresh_interval}s)"
        )
    
    def stop(self) -> None:
        """Stop the precomputation loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[OK] Async dashboard precomputer stopped")
    
    async def _precompute_loop(self) -> None:
        """Main async precomputation loop."""
        # Initial delay
        await asyncio.sleep(5)
        
        while self._running:
            try:
                await self._run_precompute_cycle()
                await asyncio.sleep(self.refresh_interval)
            except asyncio.CancelledError:
                break
            except Exception as error:
                logger.error(f"[ERROR] Async precompute failed: {error}", exc_info=True)
                await asyncio.sleep(10)
    
    async def _run_precompute_cycle(self) -> None:
        """Execute one async pre-computation cycle."""
        cycle_start = time.time()
        
        try:
            # Run CPU-heavy computations in parallel in process pool
            loop = asyncio.get_running_loop()
            pool = get_process_pool()
            
            # Prepare data for CPU workers (serialize to simple types)
            records = self.data_provider.utilization_records
            status_records = getattr(self.data_provider, 'status_records', [])
            
            util_data = [(r.site_id, r.utilization_pct) for r in records]
            status_data = [(r.site_id, r.status_code) for r in status_records]
            
            # Region data
            region_lookup = self.data_provider.region_lookup
            util_region_data = [
                (r.site_id, region_lookup.get(r.site_id, "Unknown"), r.utilization_pct)
                for r in records
            ]
            
            # Top congested data
            site_lookup = self.data_provider.site_lookup
            top_data = [
                (
                    r.circuit_id, r.site_id,
                    site_lookup.get(r.site_id, r.site_id[:8]),
                    r.utilization_pct, r.rx_bytes, r.tx_bytes
                )
                for r in records
            ]
            
            # Run CPU computations in parallel in process pool using gather
            site_statuses, util_dist, region_summary, top_congested = await asyncio.gather(
                loop.run_in_executor(
                    pool, compute_site_statuses_cpu, util_data, status_data
                ),
                loop.run_in_executor(
                    pool, compute_utilization_distribution_cpu, util_data
                ),
                loop.run_in_executor(
                    pool, compute_region_summary_cpu, util_region_data
                ),
                loop.run_in_executor(
                    pool, compute_top_congested_cpu, top_data, 10
                )
            )
            
            # Get other data (I/O bound - use to_thread for blocking calls)
            sle_summary = await asyncio.to_thread(
                self.data_provider.get_sle_summary
            )
            alarms_summary = await asyncio.to_thread(
                self.data_provider.get_alarms_summary
            )
            sle_degraded = await asyncio.to_thread(
                self.data_provider.get_sle_degraded_sites
            )
            
            # Compute alerts (light computation, run in thread)
            alerts = await asyncio.to_thread(self._compute_active_alerts)
            
            # Build dashboard data
            failover_records = getattr(self.data_provider, 'failover_records', [])
            active_failovers = len([
                r for r in failover_records
                if getattr(r, 'on_failover', False)
            ])
            
            dashboard_data = {
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
                "trends": [],  # TODO: compute trends
                "throughput": [],  # TODO: compute throughput
                "sle_summary": sle_summary,
                "alarms_summary": alarms_summary,
                "sle_degraded_sites": sle_degraded
            }
            
            # Compute other summaries in parallel
            async with asyncio.TaskGroup() as tg:
                circuit_task = tg.create_task(
                    asyncio.to_thread(self._compute_circuit_summary)
                )
                gateway_task = tg.create_task(
                    asyncio.to_thread(self._compute_gateway_health)
                )
                vpn_task = tg.create_task(
                    asyncio.to_thread(self._compute_vpn_summary)
                )
                status_bar_task = tg.create_task(
                    asyncio.to_thread(self._compute_status_bar)
                )
            
            circuit_summary = circuit_task.result()
            gateway_health = gateway_task.result()
            vpn_summary = vpn_task.result()
            status_bar = status_bar_task.result()
            
            # Store all in Redis (parallel writes)
            timestamp = datetime.now(timezone.utc).isoformat()
            
            async with asyncio.TaskGroup() as tg:
                tg.create_task(asyncio.to_thread(
                    self._store_precomputed, "main",
                    {**dashboard_data, "precomputed_at": timestamp}
                ))
                tg.create_task(asyncio.to_thread(
                    self._store_precomputed, "circuit_summary",
                    {**circuit_summary, "precomputed_at": timestamp}
                ))
                tg.create_task(asyncio.to_thread(
                    self._store_precomputed, "gateway_health",
                    {**gateway_health, "precomputed_at": timestamp}
                ))
                tg.create_task(asyncio.to_thread(
                    self._store_precomputed, "vpn_summary",
                    {**vpn_summary, "precomputed_at": timestamp}
                ))
                tg.create_task(asyncio.to_thread(
                    self._store_precomputed, "status_bar",
                    {**status_bar, "precomputed_at": timestamp}
                ))
            
            # Update stats
            self._precompute_cycles += 1
            self._last_precompute_time = time.time()
            self._last_duration_ms = (time.time() - cycle_start) * 1000
            
            if self._precompute_cycles <= 3 or self._precompute_cycles % 20 == 0:
                logger.info(
                    f"[OK] Async precompute cycle {self._precompute_cycles}: "
                    f"{self._last_duration_ms:.0f}ms"
                )
                
        except Exception as error:
            logger.error(f"[ERROR] Async precompute failed: {error}", exc_info=True)
    
    def _compute_active_alerts(self) -> List[Dict[str, Any]]:
        """Compute active alerts."""
        circuit_states = self.data_provider._get_all_circuit_states()
        return self.data_provider.current_state_views.get_active_alerts(circuit_states)
    
    def _compute_circuit_summary(self) -> Dict[str, Any]:
        """Compute circuit summary."""
        records = self.data_provider.utilization_records
        
        if not records:
            return {
                "total_circuits": 0,
                "circuits_up": 0,
                "circuits_down": getattr(self.data_provider, 'wan_down_count', 0),
                "circuits_disabled": getattr(self.data_provider, 'wan_disabled_count', 0),
                "avg_utilization": 0.0,
                "max_utilization": 0.0,
                "circuits_above_70": 0,
                "circuits_above_80": 0,
                "circuits_above_90": 0
            }
        
        circuit_ids = set(r.circuit_id for r in records)
        utils = [r.utilization_pct for r in records]
        
        return {
            "total_circuits": len(circuit_ids),
            "circuits_up": len(circuit_ids),
            "circuits_down": getattr(self.data_provider, 'wan_down_count', 0),
            "circuits_disabled": getattr(self.data_provider, 'wan_disabled_count', 0),
            "avg_utilization": round(sum(utils) / len(utils), 2) if utils else 0,
            "max_utilization": round(max(utils), 2) if utils else 0,
            "circuits_above_70": sum(1 for u in utils if u >= 70),
            "circuits_above_80": sum(1 for u in utils if u >= 80),
            "circuits_above_90": sum(1 for u in utils if u >= 90)
        }
    
    def _compute_gateway_health(self) -> Dict[str, Any]:
        """Compute gateway health summary."""
        return {
            "total": getattr(self.data_provider, 'gateways_total', 0),
            "connected": getattr(self.data_provider, 'gateways_connected', 0),
            "disconnected": getattr(self.data_provider, 'gateways_disconnected', 0)
        }
    
    def _compute_vpn_summary(self) -> Dict[str, Any]:
        """Compute VPN peer summary."""
        try:
            if hasattr(self.data_provider, 'redis_cache') and self.data_provider.redis_cache:
                summary = self.data_provider.redis_cache.get_vpn_peer_summary()
                total = summary.get("total_peers", 0)
                up = summary.get("paths_up", 0)
                down = summary.get("paths_down", 0)
                health_pct = (up / total * 100) if total > 0 else 0.0
                
                return {
                    "total_peers": total,
                    "paths_up": up,
                    "paths_down": down,
                    "health_percentage": round(health_pct, 1)
                }
        except Exception:
            pass
        
        return {"total_peers": 0, "paths_up": 0, "paths_down": 0, "health_percentage": 0}
    
    def _compute_status_bar(self) -> Dict[str, Any]:
        """Compute status bar data."""
        worker_statuses = {}
        
        # SLE worker status
        if hasattr(self.data_provider, 'sle_background_worker'):
            worker = self.data_provider.sle_background_worker
            if hasattr(worker, 'get_current_site'):
                current = worker.get_current_site()
                worker_statuses["sle"] = current if current else "idle"
            else:
                worker_statuses["sle"] = "running"
        
        # Port stats worker
        if hasattr(self.data_provider, 'background_worker'):
            worker = self.data_provider.background_worker
            if hasattr(worker, '_cycle_count'):
                worker_statuses["ports"] = f"cycle {worker._cycle_count}"
        
        # VPN worker
        if hasattr(self.data_provider, 'vpn_peer_background_worker'):
            worker = self.data_provider.vpn_peer_background_worker
            if hasattr(worker, '_collecting') and worker._collecting:
                worker_statuses["vpn"] = "collecting"
            else:
                worker_statuses["vpn"] = "idle"
        
        return {"worker_statuses": worker_statuses}
    
    def _store_precomputed(self, key: str, data: Dict[str, Any]) -> None:
        """Store pre-computed data in Redis."""
        full_key = f"{DASHBOARD_PREFIX}{key}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                self.cache.client.set(
                    full_key,
                    json.dumps(data),
                    ex=120  # 2 minute TTL
                )
        except Exception as error:
            logger.warning(f"[WARN] Failed to store precomputed {key}: {error}")
    
    def get_precomputed(self, key: str) -> Optional[Dict[str, Any]]:
        """Get pre-computed data from Redis."""
        full_key = f"{DASHBOARD_PREFIX}{key}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                data = self.cache.client.get(full_key)
                if data:
                    return json.loads(data)
        except Exception as error:
            logger.warning(f"[WARN] Failed to get precomputed {key}: {error}")
        
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get precomputer status."""
        return {
            "running": self._running,
            "precompute_cycles": self._precompute_cycles,
            "last_precompute_time": self._last_precompute_time,
            "last_duration_ms": self._last_duration_ms,
            "refresh_interval": self.refresh_interval
        }


# ==============================================================================
# Async Per-Site Precomputers
# ==============================================================================

class AsyncSitePrecomputer:
    """
    Async per-site precomputer using TaskGroup for parallel processing.
    
    Processes multiple sites concurrently using asyncio.TaskGroup,
    significantly faster than sequential batch processing.
    """
    
    def __init__(
        self,
        cache,
        data_provider,
        concurrent_sites: int = 50,
        cycle_delay: float = 1.0
    ):
        """
        Initialize the async site precomputer.
        
        Args:
            cache: Redis cache instance
            data_provider: DashboardDataProvider instance
            concurrent_sites: Number of sites to process in parallel
            cycle_delay: Seconds between full cycles
        """
        self.cache = cache
        self.data_provider = data_provider
        self.concurrent_sites = concurrent_sites
        self.cycle_delay = cycle_delay
        
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._sites_processed = 0
        self._last_cycle_time: Optional[float] = None
        self._last_cycle_duration_ms: float = 0
    
    def start(self) -> None:
        """Start the async precomputation loop."""
        if self._running:
            logger.warning("[WARN] Async site precomputer already running")
            return
        
        self._running = True
        
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        self._task = loop.create_task(self._precompute_loop())
        logger.info(
            f"[OK] Async site precomputer started "
            f"(concurrency: {self.concurrent_sites})"
        )
    
    def stop(self) -> None:
        """Stop the precomputation loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("[OK] Async site precomputer stopped")
    
    async def _precompute_loop(self) -> None:
        """Main async precomputation loop."""
        # Initial delay to let data load
        await asyncio.sleep(30)
        
        while self._running:
            try:
                await self._run_full_cycle()
                await asyncio.sleep(self.cycle_delay)
            except asyncio.CancelledError:
                break
            except Exception as error:
                logger.error(f"[ERROR] Async site precompute failed: {error}", exc_info=True)
                await asyncio.sleep(10)
    
    async def _run_full_cycle(self) -> None:
        """Process all sites in parallel batches."""
        cycle_start = time.time()
        
        sites = list(self.data_provider.site_lookup.keys())
        if not sites:
            return
        
        total_sites = len(sites)
        processed = 0
        
        # Process in batches of concurrent_sites
        for i in range(0, total_sites, self.concurrent_sites):
            if not self._running:
                break
            
            batch = sites[i:i + self.concurrent_sites]
            
            # Process batch in parallel using TaskGroup
            async with asyncio.TaskGroup() as tg:
                for site_id in batch:
                    tg.create_task(self._precompute_site(site_id))
            
            processed += len(batch)
            self._sites_processed += len(batch)
        
        # Update cycle stats
        self._cycle_count += 1
        self._last_cycle_time = time.time()
        self._last_cycle_duration_ms = (time.time() - cycle_start) * 1000
        
        if self._cycle_count <= 3 or self._cycle_count % 10 == 0:
            logger.info(
                f"[OK] Async site precompute cycle {self._cycle_count}: "
                f"{total_sites} sites in {self._last_cycle_duration_ms:.0f}ms"
            )
    
    async def _precompute_site(self, site_id: str) -> None:
        """Precompute data for a single site (to be overridden)."""
        raise NotImplementedError("Subclasses must implement _precompute_site")
    
    def get_status(self) -> Dict[str, Any]:
        """Get worker status."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "sites_processed": self._sites_processed,
            "last_cycle_time": self._last_cycle_time,
            "last_cycle_duration_ms": self._last_cycle_duration_ms
        }


class AsyncSiteSlePrecomputer(AsyncSitePrecomputer):
    """Async SLE precomputer for per-site SLE details."""
    
    async def _precompute_site(self, site_id: str) -> None:
        """Precompute SLE details for a single site."""
        try:
            # Compute SLE details (I/O bound - Redis reads)
            sle_data = await asyncio.to_thread(
                self._compute_site_sle_details, site_id
            )
            
            # Store in Redis
            await asyncio.to_thread(
                self._store_precomputed, site_id, sle_data
            )
            
        except Exception as error:
            logger.debug(f"Failed to precompute SLE for {site_id[:8]}: {error}")
    
    def _compute_site_sle_details(self, site_id: str) -> Dict[str, Any]:
        """Compute formatted SLE details for a site."""
        if not hasattr(self.data_provider, 'redis_cache') or not self.data_provider.redis_cache:
            return {"available": False, "error": "Cache not available"}
        
        cache = self.data_provider.redis_cache
        metric = "wan-link-health"
        
        try:
            summary = cache.get_site_sle_summary(site_id, metric)
            histogram = cache.get_site_sle_histogram(site_id, metric)
            gateways = cache.get_site_sle_impacted_gateways(site_id, metric)
            interfaces = cache.get_site_sle_impacted_interfaces(site_id, metric)
            last_fetch = cache.get_last_site_sle_timestamp(site_id)
            
            has_data = any([summary, histogram, gateways, interfaces])
            site_name = self.data_provider.site_lookup.get(site_id, site_id[:8] + "...")
            
            return {
                "available": has_data,
                "site_id": site_id,
                "site_name": site_name,
                "metric": metric,
                "summary": summary,
                "histogram": histogram,
                "impacted_gateways": gateways,
                "impacted_interfaces": interfaces,
                "last_fetch_timestamp": last_fetch,
                "cache_fresh": cache.is_site_sle_cache_fresh(site_id),
                "precomputed_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as error:
            return {"available": False, "error": str(error)}
    
    def _store_precomputed(self, site_id: str, data: Dict[str, Any]) -> None:
        """Store precomputed data in Redis."""
        key = f"{SITE_SLE_PREFIX}{site_id}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                self.cache.client.set(
                    key,
                    json.dumps(data),
                    ex=600  # 10 minute TTL
                )
        except Exception as error:
            logger.debug(f"Failed to store site SLE {site_id[:8]}: {error}")
    
    def get_precomputed(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Get precomputed SLE data for a site."""
        key = f"{SITE_SLE_PREFIX}{site_id}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                data = self.cache.client.get(key)
                if data:
                    return json.loads(data)
        except Exception as error:
            logger.debug(f"Failed to get site SLE {site_id[:8]}: {error}")
        
        return None


class AsyncSiteVpnPrecomputer(AsyncSitePrecomputer):
    """Async VPN precomputer for per-site VPN peer data."""
    
    async def _precompute_site(self, site_id: str) -> None:
        """Precompute VPN peer data for a single site."""
        try:
            # Compute VPN data (I/O bound - Redis reads)
            vpn_data = await asyncio.to_thread(
                self._compute_site_vpn_data, site_id
            )
            
            # Store in Redis
            await asyncio.to_thread(
                self._store_precomputed, site_id, vpn_data
            )
            
        except Exception as error:
            logger.debug(f"Failed to precompute VPN for {site_id[:8]}: {error}")
    
    def _compute_site_vpn_data(self, site_id: str) -> Dict[str, Any]:
        """Compute formatted VPN peer data for a site."""
        if not hasattr(self.data_provider, 'redis_cache') or not self.data_provider.redis_cache:
            return {"available": False, "peers": [], "error": "Cache not available"}
        
        try:
            peers = self.data_provider.redis_cache.get_site_vpn_peers(site_id)
            
            table_data = []
            site_name = self.data_provider.site_lookup.get(site_id, "Unknown")
            
            for peer in peers:
                table_data.append({
                    "site_name": site_name,
                    "vpn_name": peer.get("vpn_name", ""),
                    "peer_router_name": peer.get("peer_router_name", ""),
                    "port_id": peer.get("port_id", ""),
                    "peer_port_id": peer.get("peer_port_id", ""),
                    "status": "Up" if peer.get("up", False) else "Down",
                    "latency_ms": round(peer.get("latency", 0), 1),
                    "loss_pct": round(peer.get("loss", 0), 2),
                    "jitter_ms": round(peer.get("jitter", 0), 1),
                    "mos": round(peer.get("mos", 0), 2)
                })
            
            table_data.sort(key=lambda r: r.get("vpn_name", ""))
            
            return {
                "available": len(table_data) > 0,
                "site_id": site_id,
                "site_name": site_name,
                "peer_count": len(table_data),
                "peers": table_data,
                "precomputed_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as error:
            return {"available": False, "peers": [], "error": str(error)}
    
    def _store_precomputed(self, site_id: str, data: Dict[str, Any]) -> None:
        """Store precomputed data in Redis."""
        key = f"{SITE_VPN_PREFIX}{site_id}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                self.cache.client.set(
                    key,
                    json.dumps(data),
                    ex=600  # 10 minute TTL
                )
        except Exception as error:
            logger.debug(f"Failed to store site VPN {site_id[:8]}: {error}")
    
    def get_precomputed(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Get precomputed VPN data for a site."""
        key = f"{SITE_VPN_PREFIX}{site_id}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                data = self.cache.client.get(key)
                if data:
                    return json.loads(data)
        except Exception as error:
            logger.debug(f"Failed to get site VPN {site_id[:8]}: {error}")
        
        return None
