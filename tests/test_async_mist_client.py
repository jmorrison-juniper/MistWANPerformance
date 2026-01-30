"""
Tests for AsyncMistAPIClient

Tests the async Mist API client implementation with aiohttp.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.api.async_mist_client import (
    AsyncMistConnection,
    AsyncMistStatsOperations,
    AsyncMistAPIClient,
)
from src.utils.config import MistConfig, OperationalConfig


class TestAsyncMistConnection:
    """Tests for AsyncMistConnection class."""
    
    @pytest.fixture
    def mist_config(self):
        """Create a test Mist config."""
        return MistConfig(
            api_token="test_token",
            org_id="test_org_id",
            api_host="api.mist.com"
        )
    
    @pytest.fixture
    def ops_config(self):
        """Create a test operational config."""
        return OperationalConfig(
            rate_limit_delay=0.01,  # Fast for testing
            max_retries=2,
            retry_delay=0.01
        )
    
    @pytest.fixture
    def connection(self, mist_config, ops_config):
        """Create a test connection."""
        return AsyncMistConnection(mist_config, ops_config)
    
    def test_init_builds_correct_base_url(self, connection):
        """Test that base URL is correctly constructed."""
        assert connection.base_url == "https://api.mist.com"
    
    def test_init_builds_correct_headers(self, connection):
        """Test that auth headers are correctly set."""
        assert "Authorization" in connection.headers
        assert connection.headers["Authorization"] == "Token test_token"
        assert connection.headers["Content-Type"] == "application/json"
    
    def test_init_with_https_prefix(self, ops_config):
        """Test that existing https prefix is preserved."""
        config = MistConfig(
            api_token="test",
            org_id="org",
            api_host="https://custom.api.com"
        )
        conn = AsyncMistConnection(config, ops_config)
        assert conn.base_url == "https://custom.api.com"
    
    @pytest.mark.asyncio
    async def test_apply_rate_limit_async(self, connection):
        """Test that async rate limiting adds delay."""
        import time
        
        connection.ops_config.rate_limit_delay = 0.05  # 50ms delay
        connection._last_request_time = time.time()  # Just called
        
        start = time.time()
        await connection.apply_rate_limit_async()
        elapsed = time.time() - start
        
        # Should have waited approximately 50ms
        assert elapsed >= 0.04  # Allow some tolerance
    
    @pytest.mark.asyncio
    async def test_close_handles_no_session(self, connection):
        """Test that close() handles no session gracefully."""
        connection.session = None
        await connection.close()  # Should not raise


class TestAsyncMistStatsOperations:
    """Tests for AsyncMistStatsOperations class."""
    
    @pytest.fixture
    def mock_connection(self):
        """Create a mock connection."""
        config = MistConfig(
            api_token="test",
            org_id="test_org",
            api_host="api.mist.com"
        )
        ops_config = OperationalConfig()
        conn = AsyncMistConnection(config, ops_config)
        return conn
    
    @pytest.fixture
    def stats_ops(self, mock_connection):
        """Create stats operations with mock connection."""
        return AsyncMistStatsOperations(mock_connection)
    
    @pytest.mark.asyncio
    async def test_fetch_port_stats_page_endpoint(self, stats_ops):
        """Test that correct endpoint is called."""
        with patch.object(
            stats_ops.connection,
            'execute_get_async',
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"results": [], "next": None}
            
            await stats_ops._fetch_port_stats_page(1)
            
            # Verify endpoint path
            mock_get.assert_called_once()
            call_args = mock_get.call_args
            endpoint = call_args[0][1]
            assert "/api/v1/orgs/test_org/stats/ports/search" == endpoint
    
    @pytest.mark.asyncio
    async def test_fetch_port_stats_page_params(self, stats_ops):
        """Test that correct params are sent."""
        with patch.object(
            stats_ops.connection,
            'execute_get_async',
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"results": [], "next": None}
            
            await stats_ops._fetch_port_stats_page(
                page_number=1,
                search_after="cursor123",
                duration="2h"
            )
            
            params = mock_get.call_args[0][2]
            assert params["type"] == "gateway"
            assert params["limit"] == 1000
            assert params["duration"] == "2h"
            assert params["search_after"] == "cursor123"
    
    @pytest.mark.asyncio
    async def test_get_org_gateway_port_stats_async_single_page(self, stats_ops):
        """Test fetching single page of results."""
        test_data = [{"port_id": "1", "site_id": "site1"}]
        
        with patch.object(
            stats_ops.connection,
            'execute_get_async',
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"results": test_data, "next": None}
            
            result = await stats_ops.get_org_gateway_port_stats_async()
            
            assert len(result) == 1
            assert result[0]["port_id"] == "1"
    
    @pytest.mark.asyncio
    async def test_get_org_gateway_port_stats_async_multiple_pages(self, stats_ops):
        """Test fetching multiple pages of results."""
        page1 = [{"port_id": str(i)} for i in range(1000)]
        page2 = [{"port_id": str(i)} for i in range(1000, 1500)]
        
        call_count = 0
        
        async def mock_execute(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"results": page1, "next": "cursor1"}
            else:
                return {"results": page2, "next": None}
        
        with patch.object(
            stats_ops.connection,
            'execute_get_async',
            side_effect=mock_execute
        ):
            result = await stats_ops.get_org_gateway_port_stats_async()
            
            assert len(result) == 1500
            assert call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_org_gateway_port_stats_async_callback(self, stats_ops):
        """Test that batch callback is called."""
        test_data = [{"port_id": "1"}]
        callback_calls = []
        
        def on_batch(batch, batch_num, cursor):
            callback_calls.append((len(batch), batch_num, cursor))
        
        with patch.object(
            stats_ops.connection,
            'execute_get_async',
            new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"results": test_data, "next": None}
            
            await stats_ops.get_org_gateway_port_stats_async(on_batch=on_batch)
            
            assert len(callback_calls) == 1
            assert callback_calls[0] == (1, 1, None)


class TestAsyncMistAPIClient:
    """Tests for AsyncMistAPIClient facade."""
    
    @pytest.fixture
    def configs(self):
        """Create test configs."""
        mist_config = MistConfig(
            api_token="test",
            org_id="org",
            api_host="api.mist.com"
        )
        ops_config = OperationalConfig()
        return mist_config, ops_config
    
    def test_init_creates_connection_and_stats(self, configs):
        """Test that client initializes all components."""
        mist_config, ops_config = configs
        client = AsyncMistAPIClient(mist_config, ops_config)
        
        assert client.connection is not None
        assert client.stats is not None
        assert isinstance(client.connection, AsyncMistConnection)
        assert isinstance(client.stats, AsyncMistStatsOperations)
    
    @pytest.mark.asyncio
    async def test_context_manager(self, configs):
        """Test async context manager protocol."""
        mist_config, ops_config = configs
        
        async with AsyncMistAPIClient(mist_config, ops_config) as client:
            assert client is not None
        
        # Connection should be closed after context
        assert client.connection.session is None
    
    @pytest.mark.asyncio
    async def test_facade_delegates_to_stats(self, configs):
        """Test that facade methods delegate to stats operations."""
        mist_config, ops_config = configs
        client = AsyncMistAPIClient(mist_config, ops_config)
        
        with patch.object(
            client.stats,
            'get_org_gateway_port_stats_async',
            new_callable=AsyncMock
        ) as mock_method:
            mock_method.return_value = [{"port": "data"}]
            
            result = await client.get_org_gateway_port_stats_async()
            
            mock_method.assert_called_once()
            assert result == [{"port": "data"}]
        
        await client.close()
