"""
MistWANPerformance - Redis Cache Manager

Handles all Redis operations for caching Mist API data including:
- Organization and site data
- Gateway port statistics
- Calculated utilization records

Based on patterns from MistCircuitStats-Redis project.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Redis availability flag
REDIS_AVAILABLE = False
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    redis = None  # type: ignore[assignment]


class RedisCache:
    """
    Redis cache manager for Mist WAN performance data.
    
    Provides caching layer between API calls and dashboard,
    reducing load on Mist API and improving startup time.
    """
    
    # Cache key prefixes
    PREFIX_ORG = "mistwan:org"
    PREFIX_SITES = "mistwan:sites"
    PREFIX_SITEGROUPS = "mistwan:sitegroups"
    PREFIX_PORT_STATS = "mistwan:port_stats"
    PREFIX_UTILIZATION = "mistwan:utilization"
    PREFIX_METADATA = "mistwan:metadata"
    
    # Default TTL: 5 minutes (matches typical polling interval)
    DEFAULT_TTL = 300
    
    # Long TTL: 1 hour for rarely-changing data
    LONG_TTL = 3600
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Redis connection.
        
        Args:
            redis_url: Redis connection URL (default: from REDIS_URL env var)
        
        Raises:
            ImportError: If redis package is not installed
            ConnectionError: If cannot connect to Redis
        """
        if not REDIS_AVAILABLE:
            raise ImportError(
                "redis package is required for caching. Install with: pip install redis"
            )
        
        self.redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379")
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        
        # Test connection
        try:
            self.client.ping()
            logger.info(f"[OK] Connected to Redis at {self._safe_url()}")
        except redis.ConnectionError as error:
            logger.error(f"[ERROR] Failed to connect to Redis: {error}")
            raise ConnectionError(f"Cannot connect to Redis: {error}")
    
    def _safe_url(self) -> str:
        """Return URL with password masked for logging."""
        if "@" in self.redis_url:
            # Mask password in URL like redis://:password@host:port
            parts = self.redis_url.split("@")
            return f"***@{parts[-1]}"
        return self.redis_url
    
    def _serialize(self, data: Any) -> str:
        """Serialize data to JSON string."""
        return json.dumps(data, default=str)
    
    def _deserialize(self, data: Optional[str]) -> Any:
        """Deserialize JSON string to Python object."""
        if data is None:
            return None
        return json.loads(data)
    
    def is_connected(self) -> bool:
        """Check if Redis connection is alive."""
        try:
            self.client.ping()
            return True
        except Exception:
            return False
    
    # ==================== Metadata Operations ====================
    
    def set_last_update(self, timestamp: Optional[float] = None) -> bool:
        """
        Store the timestamp of the last successful data update.
        
        Args:
            timestamp: Unix timestamp (default: current time)
        
        Returns:
            True if successful
        """
        try:
            timestamp = timestamp or time.time()
            self.client.set(f"{self.PREFIX_METADATA}:last_update", str(timestamp))
            return True
        except Exception as error:
            logger.error(f"Error setting last update: {error}")
            return False
    
    def get_last_update(self) -> Optional[float]:
        """
        Get the timestamp of the last successful data update.
        
        Returns:
            Unix timestamp or None if never updated
        """
        try:
            data = self.client.get(f"{self.PREFIX_METADATA}:last_update")
            return float(data) if data else None
        except Exception as error:
            logger.error(f"Error getting last update: {error}")
            return None
    
    def is_cache_fresh(self, max_age_seconds: int = 300) -> bool:
        """
        Check if cached data is fresh enough to use.
        
        Args:
            max_age_seconds: Maximum age in seconds (default: 5 minutes)
        
        Returns:
            True if cache is fresh, False if stale or missing
        """
        last_update = self.get_last_update()
        if last_update is None:
            return False
        
        age = time.time() - last_update
        is_fresh = age < max_age_seconds
        
        if is_fresh:
            logger.debug(f"Cache is fresh (age: {age:.0f}s, max: {max_age_seconds}s)")
        else:
            logger.debug(f"Cache is stale (age: {age:.0f}s, max: {max_age_seconds}s)")
        
        return is_fresh
    
    def get_cache_age(self) -> Optional[float]:
        """
        Get the age of the cache in seconds.
        
        Returns:
            Age in seconds or None if no cache exists
        """
        last_update = self.get_last_update()
        if last_update is None:
            return None
        return time.time() - last_update
    
    # ==================== Organization Data ====================
    
    def set_organization(self, org_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Store organization data."""
        try:
            self.client.setex(
                self.PREFIX_ORG,
                ttl or self.LONG_TTL,
                self._serialize(org_data)
            )
            return True
        except Exception as error:
            logger.error(f"Error storing organization data: {error}")
            return False
    
    def get_organization(self) -> Optional[Dict[str, Any]]:
        """Retrieve organization data."""
        try:
            data = self.client.get(self.PREFIX_ORG)
            return self._deserialize(data)
        except Exception as error:
            logger.error(f"Error retrieving organization data: {error}")
            return None
    
    # ==================== Sites Data ====================
    
    def set_sites(self, sites: List[Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        """Store sites list."""
        try:
            self.client.setex(
                self.PREFIX_SITES,
                ttl or self.LONG_TTL,
                self._serialize(sites)
            )
            logger.debug(f"Cached {len(sites)} sites")
            return True
        except Exception as error:
            logger.error(f"Error storing sites data: {error}")
            return False
    
    def get_sites(self) -> Optional[List[Dict[str, Any]]]:
        """Retrieve sites list."""
        try:
            data = self.client.get(self.PREFIX_SITES)
            return self._deserialize(data)
        except Exception as error:
            logger.error(f"Error retrieving sites data: {error}")
            return None
    
    # ==================== Site Groups Data ====================
    
    def set_site_groups(self, sitegroups: Dict[str, str], ttl: Optional[int] = None) -> bool:
        """Store site groups mapping (id -> name)."""
        try:
            self.client.setex(
                self.PREFIX_SITEGROUPS,
                ttl or self.LONG_TTL,
                self._serialize(sitegroups)
            )
            logger.debug(f"Cached {len(sitegroups)} site groups")
            return True
        except Exception as error:
            logger.error(f"Error storing site groups: {error}")
            return False
    
    def get_site_groups(self) -> Optional[Dict[str, str]]:
        """Retrieve site groups mapping."""
        try:
            data = self.client.get(self.PREFIX_SITEGROUPS)
            return self._deserialize(data)
        except Exception as error:
            logger.error(f"Error retrieving site groups: {error}")
            return None
    
    # ==================== Port Statistics ====================
    
    def set_port_stats(self, port_stats: List[Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        """
        Store gateway port statistics.
        
        Args:
            port_stats: List of port statistics dictionaries
            ttl: Time-to-live in seconds (default: 5 minutes)
        
        Returns:
            True if successful
        """
        try:
            self.client.setex(
                self.PREFIX_PORT_STATS,
                ttl or self.DEFAULT_TTL,
                self._serialize(port_stats)
            )
            logger.info(f"[OK] Cached {len(port_stats)} port stats records")
            return True
        except Exception as error:
            logger.error(f"Error storing port stats: {error}")
            return False
    
    def get_port_stats(self) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve gateway port statistics.
        
        Returns:
            List of port statistics or None if not cached
        """
        try:
            data = self.client.get(self.PREFIX_PORT_STATS)
            result = self._deserialize(data)
            if result:
                logger.info(f"[OK] Retrieved {len(result)} port stats from cache")
            return result
        except Exception as error:
            logger.error(f"Error retrieving port stats: {error}")
            return None
    
    # ==================== Per-Site Port Statistics (Incremental Cache) ====================
    
    def set_site_port_stats(
        self,
        site_id: str,
        port_stats: List[Dict[str, Any]],
        ttl: Optional[int] = None
    ) -> bool:
        """
        Store port statistics for a specific site with timestamp.
        
        Enables incremental caching - only refresh stale sites.
        
        Args:
            site_id: The site ID
            port_stats: List of port statistics for this site
            ttl: Time-to-live in seconds (default: 1 hour)
        
        Returns:
            True if successful
        """
        try:
            key = f"{self.PREFIX_PORT_STATS}:site:{site_id}"
            data = {
                "timestamp": time.time(),
                "port_stats": port_stats
            }
            self.client.setex(
                key,
                ttl or self.LONG_TTL,
                self._serialize(data)
            )
            return True
        except Exception as error:
            logger.error(f"Error storing site port stats for {site_id}: {error}")
            return False
    
    def get_site_port_stats(self, site_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve port statistics for a specific site.
        
        Returns:
            Dictionary with 'timestamp' and 'port_stats', or None if not cached
        """
        try:
            key = f"{self.PREFIX_PORT_STATS}:site:{site_id}"
            data = self.client.get(key)
            return self._deserialize(data)
        except Exception as error:
            logger.error(f"Error retrieving site port stats for {site_id}: {error}")
            return None
    
    def is_site_cache_fresh(self, site_id: str, max_age_seconds: int = 3600) -> bool:
        """
        Check if cached data for a specific site is fresh.
        
        Args:
            site_id: The site ID to check
            max_age_seconds: Maximum age in seconds (default: 1 hour)
        
        Returns:
            True if site cache is fresh, False if stale or missing
        """
        cached = self.get_site_port_stats(site_id)
        if cached is None:
            return False
        
        timestamp = cached.get("timestamp", 0)
        age = time.time() - timestamp
        return age < max_age_seconds
    
    def get_stale_site_ids(
        self,
        site_ids: List[str],
        max_age_seconds: int = 3600
    ) -> List[str]:
        """
        Identify which sites have stale or missing cache data.
        
        Args:
            site_ids: List of site IDs to check
            max_age_seconds: Maximum cache age in seconds (default: 1 hour)
        
        Returns:
            List of site IDs that need refreshing
        """
        stale_sites = []
        fresh_sites = 0
        
        for site_id in site_ids:
            if self.is_site_cache_fresh(site_id, max_age_seconds):
                fresh_sites += 1
            else:
                stale_sites.append(site_id)
        
        logger.info(
            f"[INFO] Site cache status: {fresh_sites} fresh, "
            f"{len(stale_sites)} stale/missing (max age: {max_age_seconds}s)"
        )
        return stale_sites
    
    def get_sites_sorted_by_cache_age(
        self,
        site_ids: List[str]
    ) -> List[tuple]:
        """
        Get all sites sorted by cache age (oldest first).
        
        Sites with no cache data are returned first (infinite age).
        
        Args:
            site_ids: List of site IDs to check
        
        Returns:
            List of (site_id, age_seconds) tuples sorted by age descending
        """
        site_ages = []
        current_time = time.time()
        
        for site_id in site_ids:
            cached = self.get_site_port_stats(site_id)
            if cached is None:
                # No cache - treat as infinitely old
                site_ages.append((site_id, float('inf')))
            else:
                timestamp = cached.get("timestamp", 0)
                age = current_time - timestamp
                site_ages.append((site_id, age))
        
        # Sort by age descending (oldest first)
        site_ages.sort(key=lambda item: item[1], reverse=True)
        return site_ages
    
    def get_oldest_stale_sites(
        self,
        site_ids: List[str],
        max_age_seconds: int = 3600,
        limit: int = 50
    ) -> List[str]:
        """
        Get the oldest stale sites for priority refresh.
        
        Args:
            site_ids: List of all site IDs
            max_age_seconds: Maximum cache age before considered stale
            limit: Maximum number of sites to return
        
        Returns:
            List of site IDs sorted by age (oldest first), limited to specified count
        """
        sorted_sites = self.get_sites_sorted_by_cache_age(site_ids)
        
        # Filter to only stale sites
        stale_sites = [
            site_id for site_id, age in sorted_sites
            if age >= max_age_seconds
        ]
        
        # Return limited list
        return stale_sites[:limit]
    
    def get_all_site_port_stats(self, site_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Retrieve port statistics for all sites from per-site cache.
        
        Args:
            site_ids: List of site IDs to retrieve
        
        Returns:
            Combined list of all port statistics from cached sites
        """
        all_port_stats = []
        for site_id in site_ids:
            cached = self.get_site_port_stats(site_id)
            if cached and "port_stats" in cached:
                all_port_stats.extend(cached["port_stats"])
        
        return all_port_stats
    
    def set_bulk_site_port_stats(
        self,
        port_stats: List[Dict[str, Any]],
        ttl: Optional[int] = None
    ) -> int:
        """
        Store port statistics organized by site for incremental caching.
        
        Args:
            port_stats: List of port statistics (must contain 'site_id' field)
            ttl: Time-to-live in seconds
        
        Returns:
            Number of sites cached
        """
        # Group port stats by site_id
        by_site: Dict[str, List[Dict[str, Any]]] = {}
        for port in port_stats:
            site_id = port.get("site_id", "")
            if site_id:
                if site_id not in by_site:
                    by_site[site_id] = []
                by_site[site_id].append(port)
        
        # Store each site's data
        cached_count = 0
        for site_id, site_ports in by_site.items():
            if self.set_site_port_stats(site_id, site_ports, ttl):
                cached_count += 1
        
        logger.info(f"[OK] Cached port stats for {cached_count} sites")
        return cached_count
    
    # ==================== Utilization Records ====================
    
    def set_utilization_records(
        self,
        records: List[Dict[str, Any]],
        ttl: Optional[int] = None
    ) -> bool:
        """
        Store calculated utilization records.
        
        Args:
            records: List of utilization record dictionaries
            ttl: Time-to-live in seconds
        
        Returns:
            True if successful
        """
        try:
            self.client.setex(
                self.PREFIX_UTILIZATION,
                ttl or self.DEFAULT_TTL,
                self._serialize(records)
            )
            logger.debug(f"Cached {len(records)} utilization records")
            return True
        except Exception as error:
            logger.error(f"Error storing utilization records: {error}")
            return False
    
    def get_utilization_records(self) -> Optional[List[Dict[str, Any]]]:
        """Retrieve calculated utilization records."""
        try:
            data = self.client.get(self.PREFIX_UTILIZATION)
            return self._deserialize(data)
        except Exception as error:
            logger.error(f"Error retrieving utilization records: {error}")
            return None
    
    # ==================== Cache Management ====================
    
    def clear_all(self) -> bool:
        """
        Clear all MistWAN cache keys.
        
        Returns:
            True if successful
        """
        try:
            pattern = "mistwan:*"
            keys = self.client.keys(pattern)
            if keys:
                self.client.delete(*keys)
                logger.info(f"[OK] Cleared {len(keys)} cache keys")
            return True
        except Exception as error:
            logger.error(f"Error clearing cache: {error}")
            return False
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get statistics about cached data.
        
        Returns:
            Dictionary with cache statistics
        """
        try:
            stats = {
                "connected": self.is_connected(),
                "last_update": None,
                "cache_age_seconds": None,
                "keys": {}
            }
            
            last_update = self.get_last_update()
            if last_update:
                stats["last_update"] = datetime.fromtimestamp(
                    last_update, tz=timezone.utc
                ).isoformat()
                stats["cache_age_seconds"] = round(time.time() - last_update, 1)
            
            # Count keys by prefix
            for prefix_name in ["org", "sites", "sitegroups", "port_stats", "utilization"]:
                key = f"mistwan:{prefix_name}"
                stats["keys"][prefix_name] = self.client.exists(key)
            
            return stats
        except Exception as error:
            logger.error(f"Error getting cache stats: {error}")
            return {"connected": False, "error": str(error)}
    
    def close(self) -> None:
        """Close the Redis connection."""
        try:
            self.client.close()
            logger.debug("Redis connection closed")
        except Exception:
            pass


class NullCache:
    """
    Null cache implementation for when Redis is unavailable.
    
    All operations are no-ops, so the application can run
    without caching (always fetches from API).
    """
    
    def __init__(self):
        logger.warning("[WARN] Redis not available - caching disabled")
    
    def is_connected(self) -> bool:
        return False
    
    def is_cache_fresh(self, max_age_seconds: int = 300) -> bool:
        return False
    
    def get_cache_age(self) -> Optional[float]:
        return None
    
    def set_last_update(self, timestamp: Optional[float] = None) -> bool:
        return False
    
    def get_last_update(self) -> Optional[float]:
        return None
    
    def set_organization(self, org_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        return False
    
    def get_organization(self) -> Optional[Dict[str, Any]]:
        return None
    
    def set_sites(self, sites: List[Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        return False
    
    def get_sites(self) -> Optional[List[Dict[str, Any]]]:
        return None
    
    def set_site_groups(self, sitegroups: Dict[str, str], ttl: Optional[int] = None) -> bool:
        return False
    
    def get_site_groups(self) -> Optional[Dict[str, str]]:
        return None
    
    def set_port_stats(self, port_stats: List[Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        return False
    
    def get_port_stats(self) -> Optional[List[Dict[str, Any]]]:
        return None
    
    def set_site_port_stats(
        self,
        site_id: str,
        port_stats: List[Dict[str, Any]],
        ttl: Optional[int] = None
    ) -> bool:
        return False
    
    def get_site_port_stats(self, site_id: str) -> Optional[Dict[str, Any]]:
        return None
    
    def is_site_cache_fresh(self, site_id: str, max_age_seconds: int = 3600) -> bool:
        return False
    
    def get_stale_site_ids(
        self,
        site_ids: List[str],
        max_age_seconds: int = 3600
    ) -> List[str]:
        return list(site_ids)
    
    def get_all_site_port_stats(self, site_ids: List[str]) -> List[Dict[str, Any]]:
        return []
    
    def set_bulk_site_port_stats(
        self,
        port_stats: List[Dict[str, Any]],
        ttl: Optional[int] = None
    ) -> int:
        return 0
    
    def set_utilization_records(self, records: List[Dict[str, Any]], ttl: Optional[int] = None) -> bool:
        return False
    
    def get_utilization_records(self) -> Optional[List[Dict[str, Any]]]:
        return None
    
    def clear_all(self) -> bool:
        return True
    
    def get_cache_stats(self) -> Dict[str, Any]:
        return {"connected": False, "reason": "Redis not available"}
    
    def close(self) -> None:
        pass


def get_cache(redis_url: Optional[str] = None) -> "RedisCache | NullCache":
    """
    Factory function to get a cache instance.
    
    Returns RedisCache if available and connectable,
    otherwise returns NullCache (no-op implementation).
    
    Args:
        redis_url: Optional Redis URL override
    
    Returns:
        Cache instance (RedisCache or NullCache)
    """
    if not REDIS_AVAILABLE:
        return NullCache()
    
    try:
        return RedisCache(redis_url)
    except Exception as error:
        logger.warning(f"[WARN] Cannot connect to Redis: {error}")
        return NullCache()
