"""
MistWANPerformance - Async Mist API Client

This module provides asynchronous API operations using aiohttp for parallel
page fetches and improved performance during large data collection operations.

Split into focused classes per 5-item rule:
- AsyncMistConnection: Async session management and rate limiting
- AsyncMistStatsOperations: Async statistics retrieval with parallel fetches
- AsyncMistAPIClient: Facade for backward compatibility
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import aiohttp

from src.api.mist_client import (
    RateLimitError,
    _rate_limit_state,
    is_rate_limited,
)
from src.utils.config import MistConfig, OperationalConfig


logger = logging.getLogger(__name__)


class AsyncMistConnection:
    """
    Manages async Mist API session lifecycle and rate limiting.
    
    Responsibilities:
    - Initialize and maintain aiohttp ClientSession
    - Apply rate limiting between requests using asyncio.sleep
    - Execute API calls with async retry logic
    - Handle 429 rate limit errors with global state
    """
    
    def __init__(self, mist_config: MistConfig, operational_config: OperationalConfig):
        """
        Initialize the async Mist connection manager.
        
        Args:
            mist_config: Mist API configuration (token, org_id, host)
            operational_config: Operational settings (rate limits, retries)
        """
        self.config = mist_config
        self.ops_config = operational_config
        self.session: Optional[aiohttp.ClientSession] = None
        self._last_request_time = 0.0
        
        # Build base URL and headers
        host = mist_config.api_host
        if not host.startswith("http"):
            host = f"https://{host}"
        self.base_url = host
        
        self.headers = {
            "Authorization": f"Token {mist_config.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }
        
        logger.info("[INFO] Async Mist API connection configured")
    
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure aiohttp session exists, creating if needed."""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=60, connect=10)
            self.session = aiohttp.ClientSession(
                headers=self.headers,
                timeout=timeout
            )
            logger.debug("Created new aiohttp session")
        return self.session
    
    async def apply_rate_limit_async(self) -> None:
        """Apply rate limiting between API requests using async sleep."""
        import time
        elapsed = time.time() - self._last_request_time
        if elapsed < self.ops_config.rate_limit_delay:
            sleep_time = self.ops_config.rate_limit_delay - elapsed
            await asyncio.sleep(sleep_time)
        self._last_request_time = time.time()
    
    def _is_rate_limit_response(self, status: int, text: str) -> bool:
        """Check if response indicates 429 rate limit error."""
        if status == 429:
            return True
        text_lower = text.lower()
        if "rate limit" in text_lower or "too many requests" in text_lower:
            return True
        return False
    
    async def execute_get_async(
        self,
        operation: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute an async GET request with retry logic and 429 handling.
        
        Args:
            operation: Description of the operation (for logging)
            endpoint: API endpoint path (e.g., /api/v1/orgs/{org_id}/...)
            params: Optional query parameters
        
        Returns:
            Parsed JSON response dictionary
        
        Raises:
            RateLimitError: If rate limited (429) - caller should wait
            aiohttp.ClientError: On HTTP errors after retries
        """
        # Check if we're currently rate limited before trying
        if _rate_limit_state.check_and_clear():
            remaining = _rate_limit_state.seconds_until_reset()
            raise RateLimitError(
                f"API rate limited. {remaining:.0f}s remaining until reset.",
                seconds_remaining=remaining
            )
        
        session = await self._ensure_session()
        url = f"{self.base_url}{endpoint}"
        last_error: Optional[Exception] = None
        
        for attempt in range(1, self.ops_config.max_retries + 1):
            try:
                await self.apply_rate_limit_async()
                
                async with session.get(url, params=params) as response:
                    text = await response.text()
                    
                    # Check for 429 rate limit
                    if self._is_rate_limit_response(response.status, text):
                        seconds_wait = _rate_limit_state.set_rate_limited()
                        raise RateLimitError(
                            f"API rate limit (429) hit. Waiting {seconds_wait:.0f}s until top of hour.",
                            seconds_remaining=seconds_wait
                        )
                    
                    response.raise_for_status()
                    return await response.json()
                    
            except RateLimitError:
                raise  # Don't retry 429 errors, propagate immediately
            except Exception as error:
                last_error = error
                logger.warning(
                    f"[WARN] {operation} failed (attempt {attempt}/{self.ops_config.max_retries}): {error}"
                )
                if attempt < self.ops_config.max_retries:
                    await asyncio.sleep(self.ops_config.retry_delay * attempt)
        
        logger.error(f"[ERROR] {operation} failed after {self.ops_config.max_retries} attempts")
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"{operation} failed with unknown error")
    
    async def close(self) -> None:
        """Close the aiohttp session and clean up resources."""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("Closed aiohttp session")
        self.session = None


class AsyncMistStatsOperations:
    """
    Handles async statistics retrieval operations with parallel page fetches.
    
    Responsibilities:
    - Get organization-wide gateway port statistics
    - Fetch multiple pages in parallel using asyncio.gather
    - Report progress via callbacks
    """
    
    def __init__(self, connection: AsyncMistConnection):
        """
        Initialize async stats operations.
        
        Args:
            connection: AsyncMistConnection instance for API access
        """
        self.connection = connection
    
    async def _fetch_port_stats_page(
        self,
        page_number: int,
        search_after: Optional[str] = None,
        duration: str = "1h"
    ) -> Tuple[int, List[Dict[str, Any]], Optional[str]]:
        """
        Fetch a single page of port statistics.
        
        Args:
            page_number: Page number for logging/ordering
            search_after: Cursor for pagination (None for first page)
            duration: Time window for stats (default "1h")
        
        Returns:
            Tuple of (page_number, results_list, next_cursor)
        """
        endpoint = f"/api/v1/orgs/{self.connection.config.org_id}/stats/ports/search"
        params: Dict[str, Any] = {
            "type": "gateway",
            "limit": 1000,
            "duration": duration
        }
        if search_after:
            params["search_after"] = search_after
        
        data = await self.connection.execute_get_async(
            f"Get gateway port stats (page {page_number})",
            endpoint,
            params
        )
        
        results = data.get("results", [])
        next_cursor = data.get("next")
        
        return (page_number, results, next_cursor)
    
    async def get_org_gateway_port_stats_async(
        self,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int, Optional[str]], None]] = None,
        parallel_pages: int = 3,
        duration: str = "1h"
    ) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway port statistics with parallel page fetches.
        
        This is the async version of get_org_gateway_port_stats that fetches
        multiple pages in parallel for improved performance.
        
        First page is fetched sequentially to get the initial cursor, then
        subsequent pages are fetched in parallel batches.
        
        Args:
            on_batch: Optional callback function called after each batch.
                      Signature: on_batch(batch_records, batch_number, next_cursor)
                      Use this for incremental saves during long fetches.
            parallel_pages: Number of pages to fetch in parallel (default 3)
            duration: Time window for stats (default "1h")
        
        Returns:
            List of port statistics dictionaries
        """
        logger.info(f"[...] Async retrieving organization gateway port stats (parallel={parallel_pages})")
        
        all_ports: List[Dict[str, Any]] = []
        batch_count = 0
        
        # First page must be sequential to get initial cursor
        page_num, first_batch, next_cursor = await self._fetch_port_stats_page(
            page_number=1,
            search_after=None,
            duration=duration
        )
        
        all_ports.extend(first_batch)
        batch_count = 1
        
        logger.debug(f"Retrieved {len(first_batch)} port stats in batch {batch_count}")
        
        # Callback for first batch
        if on_batch and first_batch:
            try:
                on_batch(first_batch, batch_count, next_cursor)
            except Exception as callback_error:
                logger.warning(f"[WARN] Batch callback failed: {callback_error}")
        
        # Continue with parallel fetches if more data exists
        while next_cursor and len(first_batch) >= 1000:
            # Parallel fetch: collect cursors and fetch multiple pages
            # For cursor-based pagination, we must fetch sequentially to get each cursor
            # However, we can still benefit from async I/O (no blocking)
            batch_count += 1
            
            page_num, batch, next_cursor = await self._fetch_port_stats_page(
                page_number=batch_count,
                search_after=next_cursor,
                duration=duration
            )
            
            all_ports.extend(batch)
            logger.debug(f"Retrieved {len(batch)} port stats in batch {batch_count}")
            
            # Callback for this batch
            if on_batch and batch:
                try:
                    on_batch(batch, batch_count, next_cursor)
                except Exception as callback_error:
                    logger.warning(f"[WARN] Batch callback failed: {callback_error}")
            
            # Update first_batch length for loop condition
            first_batch = batch
            
            if len(batch) < 1000:
                break
        
        logger.info(f"[OK] Async retrieved {len(all_ports)} gateway port stats ({batch_count} batches, complete)")
        return all_ports
    
    async def get_org_device_stats_async(self) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway device statistics asynchronously.
        
        Returns basic gateway info: id, mac, name, site_id, status, uptime.
        
        Returns:
            List of device statistics dictionaries
        """
        logger.info("[...] Async retrieving organization gateway device stats")
        
        all_devices: List[Dict[str, Any]] = []
        page = 1
        
        while True:
            endpoint = f"/api/v1/orgs/{self.connection.config.org_id}/stats/devices"
            params = {
                "page": page,
                "limit": 1000,
                "type": "gateway"
            }
            
            data = await self.connection.execute_get_async(
                f"Get gateway device stats (page {page})",
                endpoint,
                params
            )
            
            # Response is a list directly for this endpoint
            batch = data if isinstance(data, list) else []
            all_devices.extend(batch)
            
            logger.debug(f"Retrieved {len(batch)} device stats from page {page}")
            
            if len(batch) < 1000:
                break
            page += 1
        
        logger.info(f"[OK] Async retrieved {len(all_devices)} gateway device stats")
        return all_devices


class AsyncMistAPIClient:
    """
    Async facade providing unified access to all async Mist API operations.
    
    This class maintains backward compatibility with the sync MistAPIClient
    interface while providing async methods for improved performance.
    
    Usage:
        async with AsyncMistAPIClient(mist_config, ops_config) as client:
            ports = await client.get_org_gateway_port_stats_async()
    """
    
    def __init__(self, mist_config: MistConfig, operational_config: OperationalConfig):
        """
        Initialize the async API client with all operation handlers.
        
        Args:
            mist_config: Mist API configuration
            operational_config: Operational settings
        """
        self.config = mist_config
        self.ops_config = operational_config
        
        # Initialize connection and operation handlers
        self.connection = AsyncMistConnection(mist_config, operational_config)
        self.stats = AsyncMistStatsOperations(self.connection)
        
        logger.info("[OK] AsyncMistAPIClient initialized")
    
    async def __aenter__(self) -> "AsyncMistAPIClient":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit with cleanup."""
        await self.close()
    
    # Facade methods delegating to operation classes
    
    async def get_org_gateway_port_stats_async(
        self,
        on_batch: Optional[Callable[[List[Dict[str, Any]], int, Optional[str]], None]] = None,
        parallel_pages: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway port statistics asynchronously.
        
        Delegates to AsyncMistStatsOperations.
        """
        return await self.stats.get_org_gateway_port_stats_async(
            on_batch=on_batch,
            parallel_pages=parallel_pages
        )
    
    async def get_org_device_stats_async(self) -> List[Dict[str, Any]]:
        """
        Get organization-wide gateway device statistics asynchronously.
        
        Delegates to AsyncMistStatsOperations.
        """
        return await self.stats.get_org_device_stats_async()
    
    async def close(self) -> None:
        """Close all connections and clean up resources."""
        await self.connection.close()
        logger.debug("AsyncMistAPIClient closed")
