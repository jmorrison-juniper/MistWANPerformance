"""
Per-Site Pre-computation Workers

Background workers that continuously precompute per-site data
(SLE details, VPN peers) so drill-down views are instant.

With 3200+ sites, we cycle through batches to avoid blocking.
Each site's data is refreshed approximately every 5-10 minutes.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Redis key prefixes for per-site precomputed data
SITE_SLE_PREFIX = "dashboard:site_sle:"
SITE_VPN_PREFIX = "dashboard:site_vpn:"


class SiteSlePrecomputer:
    """
    Pre-computes SLE details for each site.
    
    Cycles through all sites, precomputing formatted SLE data
    so drill-down views load instantly.
    """
    
    def __init__(
        self,
        cache,
        data_provider,
        batch_size: int = 50,
        cycle_delay: float = 0.5
    ):
        """
        Initialize the SLE precomputer.
        
        Args:
            cache: Redis cache instance
            data_provider: DashboardDataProvider instance
            batch_size: Sites to process per batch (default: 50)
            cycle_delay: Seconds between batches (default: 0.5)
        """
        self.cache = cache
        self.data_provider = data_provider
        self.batch_size = batch_size
        self.cycle_delay = cycle_delay
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_index = 0
        self._cycle_count = 0
        self._sites_processed = 0
        self._last_cycle_time: Optional[float] = None
    
    def start(self) -> None:
        """Start the background precomputation thread."""
        if self._running:
            logger.warning("[WARN] Site SLE precomputer already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._precompute_loop,
            name="SiteSlePrecomputer",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[OK] Site SLE precomputer started "
            f"(batch: {self.batch_size}, delay: {self.cycle_delay}s)"
        )
    
    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[OK] Site SLE precomputer stopped")
    
    def _precompute_loop(self) -> None:
        """Main precomputation loop - runs continuously without delays."""
        while self._running:
            try:
                self._process_batch()
                # No delay - stay busy, immediately process next batch
                
            except Exception as error:
                logger.error(
                    f"[ERROR] Site SLE precompute failed: {error}",
                    exc_info=True
                )
                # Brief yield to prevent CPU spin on repeated errors
                time.sleep(0.1)
    
    def _process_batch(self) -> None:
        """Process a batch of sites."""
        sites = list(self.data_provider.site_lookup.keys())
        if not sites:
            return
        
        total_sites = len(sites)
        end_index = min(self._current_index + self.batch_size, total_sites)
        batch = sites[self._current_index:end_index]
        
        for site_id in batch:
            if not self._running:
                break
            self._precompute_site_sle(site_id)
            self._sites_processed += 1
        
        # Move to next batch
        self._current_index = end_index
        
        # Check if we completed a full cycle
        if self._current_index >= total_sites:
            self._current_index = 0
            self._cycle_count += 1
            self._last_cycle_time = time.time()
            
            if self._cycle_count <= 3 or self._cycle_count % 10 == 0:
                logger.info(
                    f"[OK] Site SLE precompute cycle {self._cycle_count}: "
                    f"{total_sites} sites"
                )
    
    def _precompute_site_sle(self, site_id: str) -> None:
        """Precompute SLE details for a single site."""
        try:
            # Get the formatted SLE details
            sle_data = self._compute_site_sle_details(site_id)
            
            # Store in Redis
            self._store_precomputed(site_id, sle_data)
            
        except Exception as error:
            logger.debug(f"Failed to precompute SLE for {site_id}: {error}")
    
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
                    ex=2678400  # 31 days minimum TTL
                )
        except Exception as error:
            logger.debug(f"Failed to store site SLE {site_id}: {error}")
    
    def get_precomputed(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Get precomputed SLE data for a site."""
        key = f"{SITE_SLE_PREFIX}{site_id}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                data = self.cache.client.get(key)
                if data:
                    return json.loads(data)
        except Exception as error:
            logger.debug(f"Failed to get site SLE {site_id}: {error}")
        
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get worker status for monitoring."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "sites_processed": self._sites_processed,
            "current_index": self._current_index,
            "last_cycle_time": self._last_cycle_time
        }


class SiteVpnPrecomputer:
    """
    Pre-computes VPN peer table data for each site.
    
    Cycles through all sites, precomputing formatted VPN peer data
    so drill-down views load instantly.
    """
    
    def __init__(
        self,
        cache,
        data_provider,
        batch_size: int = 50,
        cycle_delay: float = 0.5
    ):
        """
        Initialize the VPN precomputer.
        
        Args:
            cache: Redis cache instance
            data_provider: DashboardDataProvider instance
            batch_size: Sites to process per batch (default: 50)
            cycle_delay: Seconds between batches (default: 0.5)
        """
        self.cache = cache
        self.data_provider = data_provider
        self.batch_size = batch_size
        self.cycle_delay = cycle_delay
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._current_index = 0
        self._cycle_count = 0
        self._sites_processed = 0
        self._last_cycle_time: Optional[float] = None
    
    def start(self) -> None:
        """Start the background precomputation thread."""
        if self._running:
            logger.warning("[WARN] Site VPN precomputer already running")
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._precompute_loop,
            name="SiteVpnPrecomputer",
            daemon=True
        )
        self._thread.start()
        logger.info(
            f"[OK] Site VPN precomputer started "
            f"(batch: {self.batch_size}, delay: {self.cycle_delay}s)"
        )
    
    def stop(self) -> None:
        """Stop the background thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("[OK] Site VPN precomputer stopped")
    
    def _precompute_loop(self) -> None:
        """Main precomputation loop - runs continuously without delays."""
        while self._running:
            try:
                self._process_batch()
                # No delay - stay busy, immediately process next batch
                
            except Exception as error:
                logger.error(
                    f"[ERROR] Site VPN precompute failed: {error}",
                    exc_info=True
                )
                # Brief yield to prevent CPU spin on repeated errors
                time.sleep(0.1)
    
    def _process_batch(self) -> None:
        """Process a batch of sites."""
        sites = list(self.data_provider.site_lookup.keys())
        if not sites:
            return
        
        total_sites = len(sites)
        end_index = min(self._current_index + self.batch_size, total_sites)
        batch = sites[self._current_index:end_index]
        
        for site_id in batch:
            if not self._running:
                break
            self._precompute_site_vpn(site_id)
            self._sites_processed += 1
        
        # Move to next batch
        self._current_index = end_index
        
        # Check if we completed a full cycle
        if self._current_index >= total_sites:
            self._current_index = 0
            self._cycle_count += 1
            self._last_cycle_time = time.time()
            
            if self._cycle_count <= 3 or self._cycle_count % 10 == 0:
                logger.info(
                    f"[OK] Site VPN precompute cycle {self._cycle_count}: "
                    f"{total_sites} sites"
                )
    
    def _precompute_site_vpn(self, site_id: str) -> None:
        """Precompute VPN peer data for a single site."""
        try:
            # Get the formatted VPN peer data
            vpn_data = self._compute_site_vpn_data(site_id)
            
            # Store in Redis
            self._store_precomputed(site_id, vpn_data)
            
        except Exception as error:
            logger.debug(f"Failed to precompute VPN for {site_id}: {error}")
    
    def _compute_site_vpn_data(self, site_id: str) -> Dict[str, Any]:
        """Compute formatted VPN peer data for a site."""
        if not hasattr(self.data_provider, 'redis_cache') or not self.data_provider.redis_cache:
            return {"available": False, "peers": [], "error": "Cache not available"}
        
        try:
            # Get raw VPN peers for this site
            peers = self.data_provider.redis_cache.get_site_vpn_peers(site_id)
            
            # Format for table display
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
            
            # Sort by VPN name
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
                    ex=2678400  # 31 days minimum TTL
                )
        except Exception as error:
            logger.debug(f"Failed to store site VPN {site_id}: {error}")
    
    def get_precomputed(self, site_id: str) -> Optional[Dict[str, Any]]:
        """Get precomputed VPN data for a site."""
        key = f"{SITE_VPN_PREFIX}{site_id}"
        
        try:
            if hasattr(self.cache, 'client') and self.cache.client:
                data = self.cache.client.get(key)
                if data:
                    return json.loads(data)
        except Exception as error:
            logger.debug(f"Failed to get site VPN {site_id}: {error}")
        
        return None
    
    def get_status(self) -> Dict[str, Any]:
        """Get worker status for monitoring."""
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "sites_processed": self._sites_processed,
            "current_index": self._current_index,
            "last_cycle_time": self._last_cycle_time
        }
