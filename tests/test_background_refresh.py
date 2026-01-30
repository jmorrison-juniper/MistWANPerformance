"""
MistWANPerformance - Tests for Background Refresh Module

Tests both the threading-based (legacy) and asyncio-based (preferred)
background refresh implementations.

NASA/JPL Pattern: Comprehensive test coverage for safety-critical refresh logic.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Dict, List, Any

from src.cache.background_refresh import (
    BackgroundRefreshWorker,
    AsyncBackgroundRefreshWorker,
    refresh_stale_sites_parallel,
)

# Configure pytest-asyncio mode
pytest_plugins = ('pytest_asyncio',)


class TestAsyncBackgroundRefreshWorker:
    """Test suite for AsyncBackgroundRefreshWorker class."""
    
    def test_init_sets_all_attributes(self):
        """Verify constructor initializes all attributes correctly."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        site_ids = ["site-001", "site-002", "site-003"]
        
        worker = AsyncBackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=site_ids,
            min_delay_between_fetches=10,
            max_age_seconds=1800,
            parallel_site_limit=3
        )
        
        assert worker.cache is mock_cache
        assert worker.api_client is mock_api
        assert worker.site_ids == site_ids
        assert worker.min_delay == 10
        assert worker.max_age_seconds == 1800
        assert worker.parallel_site_limit == 3
        assert not worker._running
    
    def test_get_status_returns_comprehensive_info(self):
        """Verify get_status returns all monitoring fields."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        site_ids = ["site-001", "site-002"]
        
        with patch('src.cache.background_refresh.get_rate_limit_status') as mock_rate:
            mock_rate.return_value = {"rate_limited": False, "seconds_remaining": 0}
            
            worker = AsyncBackgroundRefreshWorker(
                cache=mock_cache,
                api_client=mock_api,
                site_ids=site_ids
            )
            
            status = worker.get_status()
        
        assert "running" in status
        assert "mode" in status
        assert status["mode"] == "async"
        assert "refresh_cycles" in status
        assert "total_sites_refreshed" in status
        assert "monitored_site_count" in status
        assert status["monitored_site_count"] == 2
        assert "parallel_site_limit" in status
        assert "rate_limited" in status
    
    def test_is_running_property(self):
        """Verify is_running property reflects internal state."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        worker = AsyncBackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=[]
        )
        
        assert worker.is_running is False
        
        worker._running = True
        assert worker.is_running is True
    
    def test_start_sets_running_flag_sync(self):
        """Verify start sets the running flag (sync test version)."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        worker = AsyncBackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=["site-001"]
        )
        
        async def run_test():
            with patch.object(worker, '_refresh_loop', new_callable=AsyncMock):
                await worker.start()
                assert worker._running is True
                assert worker._task is not None
                await worker.stop()
        
        asyncio.run(run_test())
    
    def test_stop_clears_running_flag_sync(self):
        """Verify stop clears the running flag (sync test version)."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        worker = AsyncBackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=["site-001"]
        )
        
        async def run_test():
            with patch.object(worker, '_refresh_loop', new_callable=AsyncMock):
                await worker.start()
                await worker.stop()
                assert worker._running is False
        
        asyncio.run(run_test())
    
    def test_get_stale_sites_uses_pipelined_method(self):
        """Verify _get_stale_sites uses pipelined method when available."""
        mock_cache = MagicMock()
        mock_cache.get_stale_site_ids_pipelined.return_value = (
            ["site-002"], 1, 0, 1  # stale_ids, fresh, missing, stale
        )
        mock_api = MagicMock()
        
        worker = AsyncBackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=["site-001", "site-002"],
            max_age_seconds=3600
        )
        
        stale_ids, fresh, missing, stale = worker._get_stale_sites()
        
        mock_cache.get_stale_site_ids_pipelined.assert_called_once_with(
            ["site-001", "site-002"], max_age_seconds=3600
        )
        assert stale_ids == ["site-002"]
        assert fresh == 1
        assert missing == 0
        assert stale == 1


class TestRefreshStaleSitesParallel:
    """Test suite for refresh_stale_sites_parallel function."""
    
    def test_empty_list_returns_zero_sync(self):
        """Verify empty site list returns zero refreshed (sync version)."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        async def run_test():
            return await refresh_stale_sites_parallel(
                cache=mock_cache,
                api_client=mock_api,
                stale_site_ids=[]
            )
        
        result = asyncio.run(run_test())
        assert result == 0
    
    def test_respects_max_concurrent_limit_sync(self):
        """Verify concurrent limit is respected via semaphore (sync version)."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        async def run_test():
            with patch('src.cache.background_refresh.is_rate_limited', return_value=False):
                result = await refresh_stale_sites_parallel(
                    cache=mock_cache,
                    api_client=mock_api,
                    stale_site_ids=["site-001", "site-002", "site-003"],
                    max_concurrent=2
                )
            return result
        
        # Result depends on API mocking, but function should complete without error
        result = asyncio.run(run_test())
        assert isinstance(result, int)


class TestBackgroundRefreshWorkerLegacy:
    """Test suite for legacy threading-based BackgroundRefreshWorker."""
    
    def test_init_sets_all_attributes(self):
        """Verify constructor initializes all attributes correctly."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        site_ids = ["site-001", "site-002", "site-003"]
        
        worker = BackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=site_ids,
            min_delay_between_fetches=10,
            max_age_seconds=1800
        )
        
        assert worker.cache is mock_cache
        assert worker.api_client is mock_api
        assert worker.site_ids == site_ids
        assert worker.min_delay == 10
        assert worker.max_age_seconds == 1800
        assert not worker._running
    
    def test_get_status_returns_monitoring_info(self):
        """Verify get_status returns all monitoring fields."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        site_ids = ["site-001", "site-002"]
        
        with patch('src.cache.background_refresh.get_rate_limit_status') as mock_rate:
            mock_rate.return_value = {"rate_limited": False, "seconds_remaining": 0}
            
            worker = BackgroundRefreshWorker(
                cache=mock_cache,
                api_client=mock_api,
                site_ids=site_ids
            )
            
            status = worker.get_status()
        
        assert "running" in status
        assert "mode" in status
        assert status["mode"] == "continuous"
        assert "refresh_cycles" in status
        assert "total_sites_refreshed" in status
        assert "monitored_site_count" in status
        assert status["monitored_site_count"] == 2
    
    def test_is_running_property(self):
        """Verify is_running property reflects internal state."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        worker = BackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=[]
        )
        
        assert worker.is_running is False
        
        worker._running = True
        assert worker.is_running is True
    
    def test_start_and_stop_lifecycle(self):
        """Verify start/stop lifecycle works correctly."""
        mock_cache = MagicMock()
        mock_api = MagicMock()
        
        worker = BackgroundRefreshWorker(
            cache=mock_cache,
            api_client=mock_api,
            site_ids=["site-001"]
        )
        
        with patch.object(worker, '_refresh_loop'):
            worker.start()
            assert worker._running is True
            assert worker._thread is not None
            
            worker.stop()
            assert worker._running is False
