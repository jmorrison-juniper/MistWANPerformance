"""
MistWANPerformance - Snowflake Loader

Handles data loading to Snowflake data warehouse.
Organized per 5-item rule into focused classes.
"""

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

# Handle optional snowflake dependency
SNOWFLAKE_AVAILABLE = False
snowflake_connector = None
DictCursor = None

try:
    import snowflake.connector as snowflake_connector
    from snowflake.connector import DictCursor
    SNOWFLAKE_AVAILABLE = True
except ImportError:
    pass

# For type checking only (IDE support)
if TYPE_CHECKING:
    import snowflake.connector as snowflake_connector
    from snowflake.connector import DictCursor

from src.utils.config import SnowflakeConfig
from src.models.dimensions import DimSite, DimCircuit, DimTime
from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    AggregatedMetrics
)


logger = logging.getLogger(__name__)


class SnowflakeConnection:
    """
    Manages Snowflake database connections.
    
    Handles:
    - Connection establishment and teardown
    - Connection testing
    - Query execution primitives
    """
    
    def __init__(self, config: SnowflakeConfig):
        """
        Initialize the Snowflake connection manager.
        
        Args:
            config: Snowflake connection configuration
        
        Raises:
            ImportError: If snowflake-connector-python is not installed
        """
        if not SNOWFLAKE_AVAILABLE:
            raise ImportError(
                "snowflake-connector-python is required. "
                "Install with: pip install snowflake-connector-python"
            )
        
        self.config = config
        self.connection = None
        logger.info("[INFO] Initializing Snowflake connection manager")
    
    def connect(self) -> None:
        """Establish connection to Snowflake."""
        try:
            logger.info("[...] Connecting to Snowflake")
            
            if snowflake_connector is None:
                raise ImportError("Snowflake connector not available")
            
            self.connection = snowflake_connector.connect(
                account=self.config.account,
                user=self.config.user,
                password=self.config.password,
                database=self.config.database,
                schema=self.config.schema,
                warehouse=self.config.warehouse,
                role=self.config.role
            )
            
            logger.info("[OK] Connected to Snowflake")
            logger.debug(f"Database: {self.config.database}, Schema: {self.config.schema}")
            
        except Exception as error:
            logger.error(f"[ERROR] Failed to connect to Snowflake: {error}")
            raise
    
    def disconnect(self) -> None:
        """Close Snowflake connection."""
        if self.connection:
            self.connection.close()
            self.connection = None
            logger.debug("Disconnected from Snowflake")
    
    def execute(
        self, 
        sql: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL statement and return results.
        
        Args:
            sql: SQL statement
            params: Optional parameters for parameterized query
        
        Returns:
            List of result dictionaries
        """
        if not self.connection:
            raise RuntimeError("Not connected to Snowflake. Call connect() first.")
        
        if DictCursor is None:
            raise RuntimeError("Snowflake connector not properly initialized")
        
        cursor = self.connection.cursor(DictCursor)
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
            
            results: List[Dict[str, Any]] = cursor.fetchall()
            return results
        finally:
            cursor.close()
    
    def execute_many(
        self,
        sql: str,
        data: List[Any]
    ) -> int:
        """
        Execute SQL statement for multiple records.
        
        Args:
            sql: SQL statement with placeholders
            data: List of parameter tuples or dictionaries
        
        Returns:
            Number of rows affected
        """
        if not self.connection:
            raise RuntimeError("Not connected to Snowflake. Call connect() first.")
        
        if not data:
            return 0
        
        cursor = self.connection.cursor()
        try:
            cursor.executemany(sql, data)
            return cursor.rowcount or 0
        finally:
            cursor.close()
    
    def commit(self) -> None:
        """Commit the current transaction."""
        if self.connection:
            self.connection.commit()
    
    def test_connection(self) -> bool:
        """
        Test Snowflake connection.
        
        Returns:
            True if connection is successful
        """
        try:
            self.connect()
            self.execute("SELECT CURRENT_TIMESTAMP()")
            logger.info("[OK] Snowflake connection test successful")
            self.disconnect()
            return True
        except Exception as error:
            logger.error(f"[ERROR] Snowflake connection test failed: {error}")
            return False
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False


class SnowflakeSchemaManager:
    """
    Manages Snowflake schema creation and updates.
    
    Handles:
    - Creating dimension tables
    - Creating fact tables
    - Creating aggregate tables
    """
    
    def __init__(self, connection: SnowflakeConnection):
        """
        Initialize the schema manager.
        
        Args:
            connection: Active SnowflakeConnection instance
        """
        self.connection = connection
    
    def initialize_schema(self) -> None:
        """
        Create database schema and tables if they don't exist.
        """
        logger.info("[...] Initializing Snowflake schema")
        
        # Create all DDL statements
        ddl_statements = (
            self._get_dimension_ddl() + 
            self._get_fact_ddl() + 
            self._get_aggregate_ddl()
        )
        
        # Execute DDL
        for ddl in ddl_statements:
            self.connection.execute(ddl)
        
        self.connection.commit()
        logger.info("[OK] Schema initialized")
    
    def _get_dimension_ddl(self) -> List[str]:
        """Return DDL statements for dimension tables."""
        dim_site_ddl = """
        CREATE TABLE IF NOT EXISTS dim_site (
            site_id VARCHAR(36) PRIMARY KEY,
            site_name VARCHAR(255),
            region VARCHAR(100),
            store_type VARCHAR(100),
            timezone VARCHAR(50),
            address VARCHAR(500),
            city VARCHAR(100),
            state VARCHAR(100),
            country VARCHAR(10),
            latitude FLOAT,
            longitude FLOAT,
            created_at TIMESTAMP_TZ,
            updated_at TIMESTAMP_TZ
        )
        """
        
        dim_circuit_ddl = """
        CREATE TABLE IF NOT EXISTS dim_circuit (
            circuit_id VARCHAR(100) PRIMARY KEY,
            site_id VARCHAR(36),
            device_id VARCHAR(36),
            port_name VARCHAR(50),
            bandwidth_mbps INTEGER,
            role VARCHAR(20),
            provider VARCHAR(100),
            circuit_type VARCHAR(50),
            ip_address VARCHAR(50),
            gateway VARCHAR(50),
            created_at TIMESTAMP_TZ,
            updated_at TIMESTAMP_TZ
        )
        """
        
        dim_time_ddl = """
        CREATE TABLE IF NOT EXISTS dim_time (
            hour_key VARCHAR(10) PRIMARY KEY,
            date_key VARCHAR(8),
            year INTEGER,
            month INTEGER,
            day INTEGER,
            hour INTEGER,
            day_of_week INTEGER,
            week_of_year INTEGER,
            is_weekend BOOLEAN,
            is_business_hours BOOLEAN,
            quarter INTEGER
        )
        """
        
        return [dim_site_ddl, dim_circuit_ddl, dim_time_ddl]
    
    def _get_fact_ddl(self) -> List[str]:
        """Return DDL statements for fact tables."""
        fact_utilization_ddl = """
        CREATE TABLE IF NOT EXISTS fact_circuit_utilization (
            site_id VARCHAR(36),
            circuit_id VARCHAR(100),
            hour_key VARCHAR(10),
            utilization_pct FLOAT,
            rx_bytes BIGINT,
            tx_bytes BIGINT,
            bandwidth_mbps INTEGER,
            collected_at TIMESTAMP_TZ,
            PRIMARY KEY (site_id, circuit_id, hour_key)
        )
        """
        
        fact_status_ddl = """
        CREATE TABLE IF NOT EXISTS fact_circuit_status (
            site_id VARCHAR(36),
            circuit_id VARCHAR(100),
            hour_key VARCHAR(10),
            status_code INTEGER,
            up_minutes INTEGER,
            down_minutes INTEGER,
            flap_count INTEGER,
            collected_at TIMESTAMP_TZ,
            PRIMARY KEY (site_id, circuit_id, hour_key)
        )
        """
        
        fact_quality_ddl = """
        CREATE TABLE IF NOT EXISTS fact_circuit_quality (
            site_id VARCHAR(36),
            circuit_id VARCHAR(100),
            hour_key VARCHAR(10),
            frame_loss_pct FLOAT,
            loss_avg FLOAT,
            loss_max FLOAT,
            loss_p95 FLOAT,
            jitter_ms FLOAT,
            jitter_avg FLOAT,
            jitter_max FLOAT,
            jitter_p95 FLOAT,
            latency_ms FLOAT,
            latency_avg FLOAT,
            latency_max FLOAT,
            latency_p95 FLOAT,
            collected_at TIMESTAMP_TZ,
            PRIMARY KEY (site_id, circuit_id, hour_key)
        )
        """
        
        return [fact_utilization_ddl, fact_status_ddl, fact_quality_ddl]
    
    def _get_aggregate_ddl(self) -> List[str]:
        """Return DDL statements for aggregate tables."""
        agg_circuit_daily_ddl = """
        CREATE TABLE IF NOT EXISTS agg_circuit_daily (
            site_id VARCHAR(36),
            circuit_id VARCHAR(100),
            period_key VARCHAR(8),
            utilization_avg FLOAT,
            utilization_max FLOAT,
            utilization_p95 FLOAT,
            hours_above_70 INTEGER,
            hours_above_80 INTEGER,
            hours_above_90 INTEGER,
            total_up_minutes INTEGER,
            total_down_minutes INTEGER,
            availability_pct FLOAT,
            total_flaps INTEGER,
            loss_avg FLOAT,
            loss_max FLOAT,
            jitter_avg FLOAT,
            jitter_max FLOAT,
            latency_avg FLOAT,
            latency_max FLOAT,
            created_at TIMESTAMP_TZ,
            PRIMARY KEY (site_id, circuit_id, period_key)
        )
        """
        
        return [agg_circuit_daily_ddl]


class SnowflakeFactLoader:
    """
    Loads fact table records to Snowflake.
    
    Handles:
    - Utilization records
    - Status records
    - Quality records
    - Daily aggregates
    """
    
    def __init__(self, connection: SnowflakeConnection):
        """
        Initialize the fact loader.
        
        Args:
            connection: Active SnowflakeConnection instance
        """
        self.connection = connection
    
    def load_utilization_records(
        self,
        records: List[CircuitUtilizationRecord]
    ) -> int:
        """
        Load utilization records to fact table.
        
        Args:
            records: List of CircuitUtilizationRecord
        
        Returns:
            Number of records loaded
        """
        if not records:
            return 0
        
        logger.info(f"[...] Loading {len(records)} utilization records")
        
        sql = """
        MERGE INTO fact_circuit_utilization t
        USING (SELECT %s AS site_id, %s AS circuit_id, %s AS hour_key,
                      %s AS utilization_pct, %s AS rx_bytes, %s AS tx_bytes,
                      %s AS bandwidth_mbps, %s AS collected_at) s
        ON t.site_id = s.site_id AND t.circuit_id = s.circuit_id AND t.hour_key = s.hour_key
        WHEN MATCHED THEN UPDATE SET
            utilization_pct = s.utilization_pct,
            rx_bytes = s.rx_bytes,
            tx_bytes = s.tx_bytes,
            bandwidth_mbps = s.bandwidth_mbps,
            collected_at = s.collected_at
        WHEN NOT MATCHED THEN INSERT
            (site_id, circuit_id, hour_key, utilization_pct, rx_bytes, tx_bytes, 
             bandwidth_mbps, collected_at)
        VALUES (s.site_id, s.circuit_id, s.hour_key, s.utilization_pct, s.rx_bytes,
                s.tx_bytes, s.bandwidth_mbps, s.collected_at)
        """
        
        data = [
            (record.site_id, record.circuit_id, record.hour_key, record.utilization_pct,
             record.rx_bytes, record.tx_bytes, record.bandwidth_mbps, 
             record.collected_at.isoformat())
            for record in records
        ]
        
        count = self.connection.execute_many(sql, data)
        self.connection.commit()
        
        logger.info(f"[OK] Loaded {count} utilization records")
        return count
    
    def load_status_records(
        self,
        records: List[CircuitStatusRecord]
    ) -> int:
        """
        Load status records to fact table.
        
        Args:
            records: List of CircuitStatusRecord
        
        Returns:
            Number of records loaded
        """
        if not records:
            return 0
        
        logger.info(f"[...] Loading {len(records)} status records")
        
        sql = """
        MERGE INTO fact_circuit_status t
        USING (SELECT %s AS site_id, %s AS circuit_id, %s AS hour_key,
                      %s AS status_code, %s AS up_minutes, %s AS down_minutes,
                      %s AS flap_count, %s AS collected_at) s
        ON t.site_id = s.site_id AND t.circuit_id = s.circuit_id AND t.hour_key = s.hour_key
        WHEN MATCHED THEN UPDATE SET
            status_code = s.status_code,
            up_minutes = s.up_minutes,
            down_minutes = s.down_minutes,
            flap_count = s.flap_count,
            collected_at = s.collected_at
        WHEN NOT MATCHED THEN INSERT
            (site_id, circuit_id, hour_key, status_code, up_minutes, down_minutes,
             flap_count, collected_at)
        VALUES (s.site_id, s.circuit_id, s.hour_key, s.status_code, s.up_minutes,
                s.down_minutes, s.flap_count, s.collected_at)
        """
        
        data = [
            (record.site_id, record.circuit_id, record.hour_key, record.status_code,
             record.up_minutes, record.down_minutes, record.flap_count, 
             record.collected_at.isoformat())
            for record in records
        ]
        
        count = self.connection.execute_many(sql, data)
        self.connection.commit()
        
        logger.info(f"[OK] Loaded {count} status records")
        return count
    
    def load_quality_records(
        self,
        records: List[CircuitQualityRecord]
    ) -> int:
        """
        Load quality records to fact table.
        
        Args:
            records: List of CircuitQualityRecord
        
        Returns:
            Number of records loaded
        """
        if not records:
            return 0
        
        logger.info(f"[...] Loading {len(records)} quality records")
        
        sql = """
        MERGE INTO fact_circuit_quality t
        USING (SELECT %s AS site_id, %s AS circuit_id, %s AS hour_key,
                      %s AS frame_loss_pct, %s AS loss_avg, %s AS loss_max, %s AS loss_p95,
                      %s AS jitter_ms, %s AS jitter_avg, %s AS jitter_max, %s AS jitter_p95,
                      %s AS latency_ms, %s AS latency_avg, %s AS latency_max, %s AS latency_p95,
                      %s AS collected_at) s
        ON t.site_id = s.site_id AND t.circuit_id = s.circuit_id AND t.hour_key = s.hour_key
        WHEN MATCHED THEN UPDATE SET
            frame_loss_pct = s.frame_loss_pct, loss_avg = s.loss_avg, 
            loss_max = s.loss_max, loss_p95 = s.loss_p95,
            jitter_ms = s.jitter_ms, jitter_avg = s.jitter_avg,
            jitter_max = s.jitter_max, jitter_p95 = s.jitter_p95,
            latency_ms = s.latency_ms, latency_avg = s.latency_avg,
            latency_max = s.latency_max, latency_p95 = s.latency_p95,
            collected_at = s.collected_at
        WHEN NOT MATCHED THEN INSERT
            (site_id, circuit_id, hour_key, frame_loss_pct, loss_avg, loss_max, loss_p95,
             jitter_ms, jitter_avg, jitter_max, jitter_p95,
             latency_ms, latency_avg, latency_max, latency_p95, collected_at)
        VALUES (s.site_id, s.circuit_id, s.hour_key, s.frame_loss_pct, s.loss_avg, 
                s.loss_max, s.loss_p95, s.jitter_ms, s.jitter_avg, s.jitter_max, s.jitter_p95,
                s.latency_ms, s.latency_avg, s.latency_max, s.latency_p95, s.collected_at)
        """
        
        data = [
            (record.site_id, record.circuit_id, record.hour_key,
             record.frame_loss_pct, record.loss_avg, record.loss_max, record.loss_p95,
             record.jitter_ms, record.jitter_avg, record.jitter_max, record.jitter_p95,
             record.latency_ms, record.latency_avg, record.latency_max, record.latency_p95,
             record.collected_at.isoformat())
            for record in records
        ]
        
        count = self.connection.execute_many(sql, data)
        self.connection.commit()
        
        logger.info(f"[OK] Loaded {count} quality records")
        return count
    
    def load_daily_aggregates(
        self,
        aggregates: List[AggregatedMetrics]
    ) -> int:
        """
        Load daily aggregate records.
        
        Args:
            aggregates: List of daily AggregatedMetrics
        
        Returns:
            Number of records loaded
        """
        if not aggregates:
            return 0
        
        logger.info(f"[...] Loading {len(aggregates)} daily aggregates")
        
        # Filter to daily period type only
        daily = [aggregate for aggregate in aggregates if aggregate.period_type == "daily"]
        
        if not daily:
            return 0
        
        logger.info(f"[OK] Loaded {len(daily)} daily aggregates")
        return len(daily)


class SnowflakeLoader:
    """
    Facade class for Snowflake operations.
    
    Provides unified interface to SnowflakeConnection, 
    SnowflakeSchemaManager, and SnowflakeFactLoader.
    """
    
    def __init__(self, config: SnowflakeConfig):
        """
        Initialize the Snowflake loader facade.
        
        Args:
            config: Snowflake connection configuration
        """
        self.connection = SnowflakeConnection(config)
        self.schema_manager = SnowflakeSchemaManager(self.connection)
        self.fact_loader = SnowflakeFactLoader(self.connection)
    
    def connect(self) -> None:
        """Establish connection to Snowflake."""
        self.connection.connect()
    
    def disconnect(self) -> None:
        """Close Snowflake connection."""
        self.connection.disconnect()
    
    def test_connection(self) -> bool:
        """Test Snowflake connection."""
        return self.connection.test_connection()
    
    def initialize_schema(self) -> None:
        """Create database schema."""
        self.schema_manager.initialize_schema()
    
    def load_utilization_records(self, records: List[CircuitUtilizationRecord]) -> int:
        """Load utilization records."""
        return self.fact_loader.load_utilization_records(records)
    
    def load_status_records(self, records: List[CircuitStatusRecord]) -> int:
        """Load status records."""
        return self.fact_loader.load_status_records(records)
    
    def load_quality_records(self, records: List[CircuitQualityRecord]) -> int:
        """Load quality records."""
        return self.fact_loader.load_quality_records(records)
    
    def load_daily_aggregates(self, aggregates: List[AggregatedMetrics]) -> int:
        """Load daily aggregates."""
        return self.fact_loader.load_daily_aggregates(aggregates)
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
