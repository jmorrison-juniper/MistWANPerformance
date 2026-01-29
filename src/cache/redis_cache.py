"""
MistWANPerformance - Redis Cache Manager

Handles all Redis operations for caching Mist API data including:
- Organization and site data
- Gateway port statistics
- Calculated utilization records

Based on patterns from MistCircuitStats-Redis project.

Note: redis-py's type stubs use a generic ResponseT that supports both sync
and async interfaces. We use the synchronous interface only, so type: ignore
comments are used where pyright incorrectly infers async types.
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Handle optional redis dependency
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
    
    PERSISTENCE NOTE:
    -----------------
    Redis data survives restarts ONLY if persistence is enabled.
    Configure in redis.conf or via Docker:
    
    1. RDB Snapshots (periodic):
       save 900 1       # Save if 1+ keys changed in 900 seconds
       save 300 10      # Save if 10+ keys changed in 300 seconds
       save 60 10000    # Save if 10000+ keys changed in 60 seconds
    
    2. AOF (Append Only File) - recommended for durability:
       appendonly yes
       appendfsync everysec
    
    Docker example with persistence:
       docker run -d --name redis -p 6379:6379 \\
           -v redis-data:/data \\
           redis:alpine redis-server --appendonly yes
    """
    
    # Cache key prefixes
    PREFIX_ORG = "mistwan:org"
    PREFIX_SITES = "mistwan:sites"
    PREFIX_SITEGROUPS = "mistwan:sitegroups"
    PREFIX_PORT_STATS = "mistwan:port_stats"
    PREFIX_UTILIZATION = "mistwan:utilization"
    PREFIX_METADATA = "mistwan:metadata"
    PREFIX_HISTORY = "mistwan:history"
    
    # Default TTL: 5 minutes (for current/live data that changes frequently)
    DEFAULT_TTL = 300
    
    # Long TTL: 1 hour for rarely-changing reference data (org, sites)
    LONG_TTL = 3600
    
    # Historical TTL: 31 days for time-series and historical data
    # Supports 13-month rolling analysis per ProjectGoals.md
    HISTORY_TTL = 31 * 24 * 3600  # 2,678,400 seconds = 31 days
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Redis connection.
        
        Args:
            redis_url: Redis connection URL (default: from environment variables)
        
        Connection priority:
            1. Explicit redis_url parameter
            2. REDIS_URL environment variable
            3. Build from REDIS_HOST and REDIS_PORT (container-friendly)
            4. Default: redis://localhost:6379
        
        Raises:
            ImportError: If redis package is not installed
            ConnectionError: If cannot connect to Redis
        """
        if not REDIS_AVAILABLE or redis is None:
            raise ImportError(
                "redis package is required for caching. Install with: pip install redis"
            )
        
        # Build Redis URL from environment with fallback chain
        if redis_url:
            self.redis_url = redis_url
        elif os.environ.get("REDIS_URL"):
            self.redis_url = os.environ["REDIS_URL"]
        else:
            # Container-friendly: build from host/port env vars
            redis_host = os.environ.get("REDIS_HOST", "localhost")
            redis_port = os.environ.get("REDIS_PORT", "6379")
            self.redis_url = f"redis://{redis_host}:{redis_port}"
        
        # Create synchronous Redis client with string responses
        # Note: redis-py types are complex due to sync/async support
        self.client: Any = redis.from_url(self.redis_url, decode_responses=True)
        
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
        Uses 31-day retention by default to support historical analysis.
        
        Args:
            site_id: The site ID
            port_stats: List of port statistics for this site
            ttl: Time-to-live in seconds (default: 31 days)
        
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
                ttl or self.HISTORY_TTL,
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
        
        Uses Redis pipeline for efficient bulk retrieval (5-10x faster than sequential).
        
        Args:
            site_ids: List of site IDs to retrieve
        
        Returns:
            Combined list of all port statistics from cached sites
        """
        if not site_ids:
            return []
        
        # Use pipeline for bulk fetch (much faster than sequential gets)
        try:
            pipe = self.client.pipeline(transaction=False)
            keys = [f"{self.PREFIX_PORT_STATS}:site:{site_id}" for site_id in site_ids]
            
            for key in keys:
                pipe.get(key)
            
            results = pipe.execute()
            
            all_port_stats = []
            for raw_data in results:
                if raw_data is not None:
                    cached = self._deserialize(raw_data)
                    if cached and "port_stats" in cached:
                        all_port_stats.extend(cached["port_stats"])
            
            return all_port_stats
            
        except Exception as error:
            logger.warning(f"[WARN] Pipeline fetch failed, falling back to sequential: {error}")
            # Fallback to sequential fetch
            all_port_stats = []
            for site_id in site_ids:
                cached = self.get_site_port_stats(site_id)
                if cached and "port_stats" in cached:
                    all_port_stats.extend(cached["port_stats"])
            return all_port_stats
    
    def get_stale_site_ids_pipelined(
        self,
        site_ids: List[str],
        max_age_seconds: int = 3600
    ) -> tuple:
        """
        Identify stale sites using Redis pipeline for efficient bulk checking.
        
        Much faster than sequential checks for large site counts (5-10x improvement).
        
        Args:
            site_ids: List of site IDs to check
            max_age_seconds: Maximum cache age in seconds (default: 1 hour)
        
        Returns:
            Tuple of (stale_site_ids, fresh_count, missing_count, stale_count)
        """
        if not site_ids:
            return ([], 0, 0, 0)
        
        current_time = time.time()
        
        try:
            # Batch fetch all site cache entries
            pipe = self.client.pipeline(transaction=False)
            keys = [f"{self.PREFIX_PORT_STATS}:site:{site_id}" for site_id in site_ids]
            
            for key in keys:
                pipe.get(key)
            
            results = pipe.execute()
            
            stale_sites = []
            fresh_count = 0
            missing_count = 0
            stale_count = 0
            
            for site_id, raw_data in zip(site_ids, results):
                if raw_data is None:
                    # No cache data - missing
                    missing_count += 1
                    stale_sites.append(site_id)
                else:
                    cached = self._deserialize(raw_data)
                    timestamp = cached.get("timestamp", 0) if cached else 0
                    age = current_time - timestamp
                    
                    if age >= max_age_seconds:
                        stale_count += 1
                        stale_sites.append(site_id)
                    else:
                        fresh_count += 1
            
            logger.info(
                f"[INFO] Site cache status: {fresh_count} fresh, "
                f"{stale_count} stale, {missing_count} missing (max age: {max_age_seconds}s)"
            )
            return (stale_sites, fresh_count, missing_count, stale_count)
            
        except Exception as error:
            logger.warning(f"[WARN] Pipeline stale check failed, falling back to sequential: {error}")
            # Fallback to original method
            stale_sites = self.get_stale_site_ids(site_ids, max_age_seconds)
            return (stale_sites, len(site_ids) - len(stale_sites), 0, len(stale_sites))
    
    def get_sites_sorted_by_cache_age_pipelined(
        self,
        site_ids: List[str]
    ) -> List[tuple]:
        """
        Get all sites sorted by cache age using Redis pipeline.
        
        Much faster than sequential fetches for large site counts.
        Sites with no cache data are returned first (infinite age).
        
        Args:
            site_ids: List of site IDs to check
        
        Returns:
            List of (site_id, age_seconds) tuples sorted by age descending
        """
        if not site_ids:
            return []
        
        current_time = time.time()
        
        try:
            # Batch fetch all timestamps
            pipe = self.client.pipeline(transaction=False)
            keys = [f"{self.PREFIX_PORT_STATS}:site:{site_id}" for site_id in site_ids]
            
            for key in keys:
                pipe.get(key)
            
            results = pipe.execute()
            
            site_ages = []
            for site_id, raw_data in zip(site_ids, results):
                if raw_data is None:
                    site_ages.append((site_id, float('inf')))
                else:
                    cached = self._deserialize(raw_data)
                    timestamp = cached.get("timestamp", 0) if cached else 0
                    age = current_time - timestamp
                    site_ages.append((site_id, age))
            
            # Sort by age descending (oldest first)
            site_ages.sort(key=lambda item: item[1], reverse=True)
            return site_ages
            
        except Exception as error:
            logger.warning(f"[WARN] Pipeline age sort failed, falling back to sequential: {error}")
            return self.get_sites_sorted_by_cache_age(site_ids)
    
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
    
    # ==================== Historical Time-Series Data ====================
    
    def append_historical_record(
        self,
        site_id: str,
        circuit_id: str,
        record: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        """
        Append a utilization record to historical time-series.
        
        Uses Redis Sorted Set with timestamp as score for efficient
        time-range queries. Data retained for 31 days by default.
        
        Args:
            site_id: Site identifier
            circuit_id: Circuit/port identifier
            record: Record containing timestamp and metrics
            ttl: Time-to-live in seconds (default: 31 days)
        
        Returns:
            True if successful
        """
        try:
            key = f"{self.PREFIX_HISTORY}:{site_id}:{circuit_id}"
            timestamp = record.get("timestamp", time.time())
            
            # Add to sorted set with timestamp as score
            self.client.zadd(key, {self._serialize(record): timestamp})
            
            # Set/refresh expiry on the key
            self.client.expire(key, ttl or self.HISTORY_TTL)
            
            return True
        except Exception as error:
            logger.error(f"Error appending historical record: {error}")
            return False
    
    def get_historical_records(
        self,
        site_id: str,
        circuit_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Retrieve historical records for a circuit within a time range.
        
        Args:
            site_id: Site identifier
            circuit_id: Circuit/port identifier
            start_time: Start timestamp (default: 31 days ago)
            end_time: End timestamp (default: now)
            limit: Maximum records to return
        
        Returns:
            List of historical records sorted by timestamp
        """
        try:
            key = f"{self.PREFIX_HISTORY}:{site_id}:{circuit_id}"
            
            # Default to last 31 days
            end_time = end_time or time.time()
            start_time = start_time or (end_time - self.HISTORY_TTL)
            
            # Get records in time range
            raw_records = self.client.zrangebyscore(
                key, start_time, end_time, start=0, num=limit
            )
            
            records = [self._deserialize(record) for record in raw_records]
            return records
        except Exception as error:
            logger.error(f"Error retrieving historical records: {error}")
            return []
    
    def prune_old_history(self, site_id: str, circuit_id: str, max_age_seconds: Optional[int] = None) -> int:
        """
        Remove historical records older than max age.
        
        Args:
            site_id: Site identifier
            circuit_id: Circuit/port identifier
            max_age_seconds: Maximum age in seconds (default: 31 days)
        
        Returns:
            Number of records removed
        """
        try:
            key = f"{self.PREFIX_HISTORY}:{site_id}:{circuit_id}"
            max_age = max_age_seconds or self.HISTORY_TTL
            cutoff = time.time() - max_age
            
            removed = self.client.zremrangebyscore(key, "-inf", cutoff)
            if removed > 0:
                logger.debug(f"Pruned {removed} old records from {key}")
            return removed
        except Exception as error:
            logger.error(f"Error pruning history: {error}")
            return 0
    
    def get_history_stats(self) -> Dict[str, Any]:
        """
        Get statistics about historical data storage.
        
        Returns:
            Dictionary with history statistics
        """
        try:
            pattern = f"{self.PREFIX_HISTORY}:*"
            keys = self.client.keys(pattern)
            
            total_records = 0
            oldest_record = None
            newest_record = None
            
            for key in keys[:100]:  # Sample first 100 keys for stats
                count = self.client.zcard(key)
                total_records += count
                
                # Get oldest and newest timestamps
                oldest = self.client.zrange(key, 0, 0, withscores=True)
                newest = self.client.zrange(key, -1, -1, withscores=True)
                
                if oldest:
                    timestamp = oldest[0][1]
                    if oldest_record is None or timestamp < oldest_record:
                        oldest_record = timestamp
                
                if newest:
                    timestamp = newest[0][1]
                    if newest_record is None or timestamp > newest_record:
                        newest_record = timestamp
            
            return {
                "circuit_count": len(keys),
                "total_records_sampled": total_records,
                "oldest_record": datetime.fromtimestamp(oldest_record, tz=timezone.utc).isoformat() if oldest_record else None,
                "newest_record": datetime.fromtimestamp(newest_record, tz=timezone.utc).isoformat() if newest_record else None,
                "retention_days": self.HISTORY_TTL // 86400
            }
        except Exception as error:
            logger.error(f"Error getting history stats: {error}")
            return {"error": str(error)}
    
    # ==================== Utilization Trends Storage ====================
    
    # Key for storing periodic utilization snapshots for trends chart
    PREFIX_TRENDS = "mistwan:trends"
    TRENDS_TTL = 86400 * 7  # 7 days retention for trends
    
    def store_utilization_snapshot(
        self,
        avg_utilization: float,
        max_utilization: float,
        circuit_count: int,
        total_rx_bytes: int = 0,
        total_tx_bytes: int = 0,
        timestamp: Optional[float] = None
    ) -> bool:
        """
        Store a periodic snapshot of utilization metrics for trends.
        
        Called during each data refresh to build historical trends.
        Uses Redis Sorted Set for efficient time-range queries.
        
        Args:
            avg_utilization: Average utilization across all circuits
            max_utilization: Maximum utilization seen
            circuit_count: Number of circuits in snapshot
            total_rx_bytes: Total received bytes (cumulative)
            total_tx_bytes: Total transmitted bytes (cumulative)
            timestamp: Snapshot timestamp (default: now)
        
        Returns:
            True if successful
        """
        try:
            timestamp = timestamp or time.time()
            snapshot = {
                "timestamp": timestamp,
                "avg_utilization": round(avg_utilization, 2),
                "max_utilization": round(max_utilization, 2),
                "circuit_count": circuit_count,
                "total_rx_bytes": total_rx_bytes,
                "total_tx_bytes": total_tx_bytes
            }
            
            key = f"{self.PREFIX_TRENDS}:snapshots"
            self.client.zadd(key, {self._serialize(snapshot): timestamp})
            self.client.expire(key, self.TRENDS_TTL)
            
            # Prune old snapshots beyond retention period
            cutoff = time.time() - self.TRENDS_TTL
            self.client.zremrangebyscore(key, "-inf", cutoff)
            
            return True
        except Exception as error:
            logger.error(f"Error storing utilization snapshot: {error}")
            return False
    
    def get_utilization_trends(
        self,
        hours: int = 24,
        interval_minutes: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Retrieve utilization trends for the specified time range.
        
        Args:
            hours: Number of hours of history to retrieve
            interval_minutes: Target interval between points (for downsampling)
        
        Returns:
            List of trend data points sorted by timestamp
        """
        try:
            key = f"{self.PREFIX_TRENDS}:snapshots"
            end_time = time.time()
            start_time = end_time - (hours * 3600)
            
            # Get all snapshots in time range
            raw_snapshots = self.client.zrangebyscore(
                key, start_time, end_time, withscores=True
            )
            
            if not raw_snapshots:
                return []
            
            # Parse snapshots
            snapshots = []
            for data, score in raw_snapshots:
                try:
                    snapshot = self._deserialize(data)
                    snapshot["_score"] = score
                    snapshots.append(snapshot)
                except Exception:
                    continue
            
            # Downsample if too many points (target ~100-200 points max)
            max_points = max(1, (hours * 60) // interval_minutes)
            if len(snapshots) > max_points * 2:
                # Keep every Nth point
                step = len(snapshots) // max_points
                snapshots = snapshots[::step]
            
            # Format for chart display
            trends = []
            for snapshot in snapshots:
                ts = snapshot.get("timestamp", snapshot.get("_score", 0))
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                trends.append({
                    "timestamp": dt.strftime("%H:%M"),
                    "datetime": dt.isoformat(),
                    "avg_utilization": snapshot.get("avg_utilization", 0),
                    "max_utilization": snapshot.get("max_utilization", 0),
                    "circuit_count": snapshot.get("circuit_count", 0),
                    "total_rx_bytes": snapshot.get("total_rx_bytes", 0),
                    "total_tx_bytes": snapshot.get("total_tx_bytes", 0)
                })
            
            return trends
        except Exception as error:
            logger.error(f"Error retrieving utilization trends: {error}")
            return []
    
    def get_throughput_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get cumulative throughput history for throughput chart.
        
        Returns delta bytes between snapshots (actual throughput).
        
        Args:
            hours: Number of hours of history
        
        Returns:
            List of throughput data points with rx/tx rates
        """
        try:
            trends = self.get_utilization_trends(hours=hours, interval_minutes=5)
            if len(trends) < 2:
                return trends
            
            # Calculate deltas between consecutive snapshots
            throughput = []
            for i in range(1, len(trends)):
                prev = trends[i - 1]
                curr = trends[i]
                
                # Calculate time delta in seconds
                prev_ts = datetime.fromisoformat(prev["datetime"])
                curr_ts = datetime.fromisoformat(curr["datetime"])
                delta_seconds = max(1, (curr_ts - prev_ts).total_seconds())
                
                # Calculate byte deltas (handle counter resets)
                rx_delta = curr["total_rx_bytes"] - prev["total_rx_bytes"]
                tx_delta = curr["total_tx_bytes"] - prev["total_tx_bytes"]
                
                # Handle counter resets (negative deltas)
                if rx_delta < 0:
                    rx_delta = curr["total_rx_bytes"]
                if tx_delta < 0:
                    tx_delta = curr["total_tx_bytes"]
                
                # Convert to Mbps
                rx_mbps = (rx_delta * 8) / (delta_seconds * 1_000_000)
                tx_mbps = (tx_delta * 8) / (delta_seconds * 1_000_000)
                
                throughput.append({
                    "timestamp": curr["timestamp"],
                    "datetime": curr["datetime"],
                    "rx_mbps": round(rx_mbps, 2),
                    "tx_mbps": round(tx_mbps, 2),
                    "rx_bytes": rx_delta,
                    "tx_bytes": tx_delta
                })
            
            return throughput
        except Exception as error:
            logger.error(f"Error calculating throughput history: {error}")
            return []
    
    # ==================== Incremental Fetch Progress ====================
    
    # Key prefix for tracking fetch progress
    PREFIX_FETCH_PROGRESS = "mistwan:fetch_progress"
    
    def start_fetch_session(self, session_id: Optional[str] = None) -> str:
        """
        Start a new fetch session for tracking incremental progress.
        
        Args:
            session_id: Optional session ID (default: timestamp-based)
        
        Returns:
            Session ID string
        """
        try:
            session_id = session_id or f"fetch_{int(time.time())}"
            progress_data = {
                "session_id": session_id,
                "started_at": time.time(),
                "batches_completed": 0,
                "records_saved": 0,
                "sites_saved": [],
                "status": "in_progress",
                "last_cursor": None
            }
            
            key = f"{self.PREFIX_FETCH_PROGRESS}:{session_id}"
            self.client.setex(
                key,
                3600,  # 1 hour TTL for fetch progress
                self._serialize(progress_data)
            )
            
            # Mark this as the current active session
            self.client.set(f"{self.PREFIX_FETCH_PROGRESS}:current", session_id)
            
            logger.info(f"[INFO] Started fetch session: {session_id}")
            return session_id
        except Exception as error:
            logger.error(f"Error starting fetch session: {error}")
            return f"fetch_{int(time.time())}"
    
    def update_fetch_progress(
        self,
        session_id: str,
        batch_number: int,
        records_in_batch: int,
        sites_in_batch: List[str],
        cursor: Optional[str] = None
    ) -> bool:
        """
        Update fetch progress after saving a batch.
        
        Args:
            session_id: Fetch session ID
            batch_number: Current batch number
            records_in_batch: Number of records in this batch
            sites_in_batch: List of site IDs in this batch
            cursor: Pagination cursor for resuming
        
        Returns:
            True if successful
        """
        try:
            key = f"{self.PREFIX_FETCH_PROGRESS}:{session_id}"
            data = self.client.get(key)
            
            if not data:
                logger.warning(f"Fetch session {session_id} not found")
                return False
            
            progress = self._deserialize(data)
            progress["batches_completed"] = batch_number
            progress["records_saved"] = progress.get("records_saved", 0) + records_in_batch
            progress["last_cursor"] = cursor
            progress["last_updated"] = time.time()
            
            # Track unique sites saved
            existing_sites = set(progress.get("sites_saved", []))
            existing_sites.update(sites_in_batch)
            progress["sites_saved"] = list(existing_sites)
            
            self.client.setex(key, 3600, self._serialize(progress))
            return True
        except Exception as error:
            logger.error(f"Error updating fetch progress: {error}")
            return False
    
    def complete_fetch_session(self, session_id: str, status: str = "completed") -> bool:
        """
        Mark a fetch session as complete.
        
        Args:
            session_id: Fetch session ID
            status: Final status ("completed", "failed", "interrupted")
        
        Returns:
            True if successful
        """
        try:
            key = f"{self.PREFIX_FETCH_PROGRESS}:{session_id}"
            data = self.client.get(key)
            
            if not data:
                return False
            
            progress = self._deserialize(data)
            progress["status"] = status
            progress["completed_at"] = time.time()
            
            # Keep completed sessions for a day for debugging
            self.client.setex(key, 86400, self._serialize(progress))
            
            # Clear current session marker
            self.client.delete(f"{self.PREFIX_FETCH_PROGRESS}:current")
            
            logger.info(
                f"[OK] Fetch session {status}: {progress.get('batches_completed', 0)} batches, "
                f"{progress.get('records_saved', 0)} records, "
                f"{len(progress.get('sites_saved', []))} sites"
            )
            return True
        except Exception as error:
            logger.error(f"Error completing fetch session: {error}")
            return False
    
    def get_fetch_progress(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get progress of a fetch session.
        
        Args:
            session_id: Session ID (default: current active session)
        
        Returns:
            Progress dictionary or None if not found
        """
        try:
            if not session_id:
                session_id = self.client.get(f"{self.PREFIX_FETCH_PROGRESS}:current")
                if not session_id:
                    return None
            
            key = f"{self.PREFIX_FETCH_PROGRESS}:{session_id}"
            data = self.client.get(key)
            return self._deserialize(data) if data else None
        except Exception as error:
            logger.error(f"Error getting fetch progress: {error}")
            return None
    
    def get_incomplete_fetch_session(self) -> Optional[Dict[str, Any]]:
        """
        Check if there's an incomplete fetch session that can be resumed.
        
        Returns:
            Progress dictionary if resumable session exists, None otherwise
        """
        progress = self.get_fetch_progress()
        
        if progress and progress.get("status") == "in_progress":
            # Check if it's not too old (max 1 hour)
            started_at = progress.get("started_at", 0)
            age = time.time() - started_at
            
            if age < 3600:
                logger.info(
                    f"[INFO] Found incomplete fetch session: "
                    f"{progress.get('batches_completed', 0)} batches saved, "
                    f"{len(progress.get('sites_saved', []))} sites cached"
                )
                return progress
            else:
                logger.info("[INFO] Previous fetch session too old to resume")
        
        return None
    
    def save_batch_incrementally(
        self,
        port_stats: List[Dict[str, Any]],
        session_id: str,
        batch_number: int,
        cursor: Optional[str] = None
    ) -> int:
        """
        Save a batch of port stats immediately and update progress.
        
        This is the key method for incremental saves - each batch is
        persisted to Redis as it arrives from the API.
        
        Args:
            port_stats: List of port statistics from this batch
            session_id: Fetch session ID
            batch_number: Current batch number
            cursor: Pagination cursor for next batch
        
        Returns:
            Number of sites saved in this batch
        """
        if not port_stats:
            return 0
        
        # Group by site_id
        by_site: Dict[str, List[Dict[str, Any]]] = {}
        for port in port_stats:
            site_id = port.get("site_id", "")
            if site_id:
                if site_id not in by_site:
                    by_site[site_id] = []
                by_site[site_id].append(port)
        
        # Save each site's data incrementally (append to existing if present)
        sites_saved = []
        for site_id, site_ports in by_site.items():
            if self._append_site_port_stats(site_id, site_ports):
                sites_saved.append(site_id)
        
        # Update progress tracker
        self.update_fetch_progress(
            session_id=session_id,
            batch_number=batch_number,
            records_in_batch=len(port_stats),
            sites_in_batch=sites_saved,
            cursor=cursor
        )
        
        logger.debug(
            f"[...] Batch {batch_number}: saved {len(port_stats)} records "
            f"for {len(sites_saved)} sites"
        )
        
        return len(sites_saved)
    
    def _append_site_port_stats(
        self,
        site_id: str,
        new_port_stats: List[Dict[str, Any]]
    ) -> bool:
        """
        Append port stats to a site's existing cache (or create new).
        
        This handles the case where a site's data arrives across multiple
        batches - we merge rather than replace.
        
        Args:
            site_id: The site ID
            new_port_stats: New port statistics to add
        
        Returns:
            True if successful
        """
        try:
            key = f"{self.PREFIX_PORT_STATS}:site:{site_id}"
            existing = self.get_site_port_stats(site_id)
            
            if existing and "port_stats" in existing:
                # Merge: keep existing ports, add/update new ones
                existing_ports = {
                    (p.get("mac", ""), p.get("port_id", "")): p
                    for p in existing["port_stats"]
                }
                
                for port in new_port_stats:
                    port_key = (port.get("mac", ""), port.get("port_id", ""))
                    existing_ports[port_key] = port
                
                merged_stats = list(existing_ports.values())
            else:
                merged_stats = new_port_stats
            
            data = {
                "timestamp": time.time(),
                "port_stats": merged_stats
            }
            
            self.client.setex(
                key,
                self.HISTORY_TTL,
                self._serialize(data)
            )
            return True
        except Exception as error:
            logger.error(f"Error appending site port stats for {site_id}: {error}")
            return False

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
                "keys": {},
                "persistence": {},
                "history": {}
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
            
            # Count per-site port stats and history keys
            site_keys = self.client.keys(f"{self.PREFIX_PORT_STATS}:site:*")
            stats["keys"]["per_site_port_stats"] = len(site_keys)
            
            history_keys = self.client.keys(f"{self.PREFIX_HISTORY}:*")
            stats["keys"]["history_series"] = len(history_keys)
            
            # Get persistence configuration
            stats["persistence"] = self.get_persistence_config()
            
            # Get history stats
            stats["history"] = self.get_history_stats()
            
            return stats
        except Exception as error:
            logger.error(f"Error getting cache stats: {error}")
            return {"connected": False, "error": str(error)}
    
    def get_persistence_config(self) -> Dict[str, Any]:
        """
        Check Redis persistence configuration.
        
        Returns:
            Dictionary with persistence status and recommendations
        """
        try:
            info = self.client.info("persistence")
            
            rdb_enabled = info.get("rdb_bgsave_in_progress", 0) >= 0
            aof_enabled = info.get("aof_enabled", 0) == 1
            
            # Check last save time
            last_rdb_save = info.get("rdb_last_save_time", 0)
            last_save_ago = time.time() - last_rdb_save if last_rdb_save else None
            
            config = {
                "rdb_enabled": rdb_enabled,
                "aof_enabled": aof_enabled,
                "last_rdb_save": datetime.fromtimestamp(last_rdb_save, tz=timezone.utc).isoformat() if last_rdb_save else None,
                "last_save_ago_seconds": round(last_save_ago, 0) if last_save_ago else None,
                "aof_rewrite_in_progress": info.get("aof_rewrite_in_progress", 0) == 1,
                "data_is_persisted": aof_enabled or (rdb_enabled and last_rdb_save > 0)
            }
            
            # Add warning if no persistence
            if not config["data_is_persisted"]:
                config["warning"] = (
                    "Redis persistence is NOT configured! Data will be lost on restart. "
                    "Enable AOF with: redis-server --appendonly yes"
                )
            
            return config
        except Exception as error:
            logger.error(f"Error checking persistence config: {error}")
            return {"error": str(error)}
    
    def force_save(self) -> bool:
        """
        Force Redis to save data to disk immediately.
        
        Uses BGSAVE for RDB snapshot (non-blocking).
        
        Returns:
            True if save initiated successfully
        """
        try:
            self.client.bgsave()
            logger.info("[OK] Redis background save initiated")
            return True
        except Exception as error:
            # BGSAVE may fail if already in progress
            if "Background save already in progress" in str(error):
                logger.info("[INFO] Redis save already in progress")
                return True
            logger.error(f"Error forcing save: {error}")
            return False
    
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
    
    def get_sites_sorted_by_cache_age(
        self,
        site_ids: List[str]
    ) -> List[tuple]:
        """Return all sites as missing (infinite age)."""
        return [(site_id, float('inf')) for site_id in site_ids]
    
    def get_all_site_port_stats(self, site_ids: List[str]) -> List[Dict[str, Any]]:
        return []
    
    def get_stale_site_ids_pipelined(
        self,
        site_ids: List[str],
        max_age_seconds: int = 3600
    ) -> tuple:
        """Return all sites as stale (NullCache has no data)."""
        return (list(site_ids), 0, len(site_ids), 0)
    
    def get_sites_sorted_by_cache_age_pipelined(
        self,
        site_ids: List[str]
    ) -> List[tuple]:
        """Return all sites as missing (infinite age)."""
        return [(site_id, float('inf')) for site_id in site_ids]
    
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
    
    def append_historical_record(
        self,
        site_id: str,
        circuit_id: str,
        record: Dict[str, Any],
        ttl: Optional[int] = None
    ) -> bool:
        return False
    
    def get_historical_records(
        self,
        site_id: str,
        circuit_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        return []
    
    def prune_old_history(self, site_id: str, circuit_id: str, max_age_seconds: Optional[int] = None) -> int:
        return 0
    
    def get_history_stats(self) -> Dict[str, Any]:
        return {"error": "Redis not available"}
    
    def get_persistence_config(self) -> Dict[str, Any]:
        return {"error": "Redis not available"}
    
    def force_save(self) -> bool:
        return False
    
    # Utilization trends stubs
    def store_utilization_snapshot(
        self,
        avg_utilization: float,
        max_utilization: float,
        circuit_count: int,
        total_rx_bytes: int = 0,
        total_tx_bytes: int = 0,
        timestamp: Optional[float] = None
    ) -> bool:
        return False
    
    def get_utilization_trends(
        self,
        hours: int = 24,
        interval_minutes: int = 5
    ) -> List[Dict[str, Any]]:
        return []
    
    def get_throughput_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        return []
    
    # Incremental fetch progress stubs
    def start_fetch_session(self, session_id: Optional[str] = None) -> str:
        return f"null_fetch_{int(time.time())}"
    
    def update_fetch_progress(
        self,
        session_id: str,
        batch_number: int,
        records_in_batch: int,
        sites_in_batch: List[str],
        cursor: Optional[str] = None
    ) -> bool:
        return False
    
    def complete_fetch_session(self, session_id: str, status: str = "completed") -> bool:
        return False
    
    def get_fetch_progress(self, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return None
    
    def get_incomplete_fetch_session(self) -> Optional[Dict[str, Any]]:
        return None
    
    def save_batch_incrementally(
        self,
        port_stats: List[Dict[str, Any]],
        session_id: str,
        batch_number: int,
        cursor: Optional[str] = None
    ) -> int:
        return 0
    
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
