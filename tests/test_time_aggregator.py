"""
MistWANPerformance - Time Aggregator Tests

Unit tests for rolling window and time aggregation logic.
"""

import unittest
from datetime import datetime, timezone, timedelta

from src.aggregators.time_aggregator import TimeAggregator
from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    RollingWindowMetrics
)


class TestTimeAggregatorRollingWindows(unittest.TestCase):
    """Test cases for rolling window calculations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.aggregator = TimeAggregator()
        self.test_site_id = "test-site-001"
        self.test_circuit_id = "test-device:wan0"
    
    def _create_utilization_record(
        self,
        hour_key: str,
        utilization_pct: float
    ) -> CircuitUtilizationRecord:
        """Helper to create test utilization record."""
        return CircuitUtilizationRecord(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            hour_key=hour_key,
            utilization_pct=utilization_pct,
            rx_bytes=1000000,
            tx_bytes=500000,
            bandwidth_mbps=100,
            collected_at=datetime.now(timezone.utc)
        )
    
    def _create_status_record(
        self,
        hour_key: str,
        up_minutes: int,
        down_minutes: int,
        flap_count: int
    ) -> CircuitStatusRecord:
        """Helper to create test status record."""
        return CircuitStatusRecord(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            hour_key=hour_key,
            status_code=1 if up_minutes > 0 else 0,
            up_minutes=up_minutes,
            down_minutes=down_minutes,
            flap_count=flap_count,
            collected_at=datetime.now(timezone.utc)
        )
    
    def _create_quality_record(
        self,
        hour_key: str,
        loss_avg: float,
        jitter_avg: float,
        latency_avg: float
    ) -> CircuitQualityRecord:
        """Helper to create test quality record."""
        return CircuitQualityRecord(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            hour_key=hour_key,
            loss_avg=loss_avg,
            jitter_avg=jitter_avg,
            latency_avg=latency_avg,
            collected_at=datetime.now(timezone.utc)
        )
    
    def test_rolling_window_3h_utilization_avg(self):
        """Test 3-hour rolling window calculates correct average."""
        # Create 3 hours of data
        records = [
            self._create_utilization_record("2024010110", 60.0),
            self._create_utilization_record("2024010111", 70.0),
            self._create_utilization_record("2024010112", 80.0),
        ]
        
        window_end = datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc)
        
        result = self.aggregator.calculate_rolling_window(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            utilization_records=records,
            status_records=[],
            quality_records=[],
            window_hours=3,
            window_end=window_end
        )
        
        # Average of 60, 70, 80 = 70
        self.assertIsNotNone(result.utilization_avg)
        self.assertAlmostEqual(result.utilization_avg or 0.0, 70.0, places=1)
        self.assertEqual(result.window_hours, 3)
    
    def test_rolling_window_continuous_hours_above_threshold(self):
        """Test continuous hours above threshold calculation."""
        # Create pattern: below, above, above, above (3 consecutive)
        records = [
            self._create_utilization_record("2024010109", 65.0),
            self._create_utilization_record("2024010110", 75.0),
            self._create_utilization_record("2024010111", 78.0),
            self._create_utilization_record("2024010112", 72.0),
        ]
        
        window_end = datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)
        
        result = self.aggregator.calculate_rolling_window(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            utilization_records=records,
            status_records=[],
            quality_records=[],
            window_hours=4,
            window_end=window_end
        )
        
        # 3 consecutive hours above 70%
        self.assertEqual(result.continuous_hours_above_70, 3.0)
    
    def test_rolling_window_cumulative_hours_above_threshold(self):
        """Test cumulative hours above threshold calculation."""
        # Create pattern: below, above, below, above
        records = [
            self._create_utilization_record("2024010109", 65.0),
            self._create_utilization_record("2024010110", 75.0),  # Above
            self._create_utilization_record("2024010111", 68.0),
            self._create_utilization_record("2024010112", 85.0),  # Above
        ]
        
        window_end = datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)
        
        result = self.aggregator.calculate_rolling_window(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            utilization_records=records,
            status_records=[],
            quality_records=[],
            window_hours=4,
            window_end=window_end
        )
        
        # 2 total hours above 70% (not consecutive)
        self.assertEqual(result.cumulative_hours_above_70, 2.0)
    
    def test_rolling_window_availability_calculation(self):
        """Test availability percentage in rolling window."""
        records = [
            self._create_status_record("2024010110", 60, 0, 0),
            self._create_status_record("2024010111", 30, 30, 1),
            self._create_status_record("2024010112", 60, 0, 0),
        ]
        
        window_end = datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)
        
        result = self.aggregator.calculate_rolling_window(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            utilization_records=[],
            status_records=records,
            quality_records=[],
            window_hours=3,
            window_end=window_end
        )
        
        # 150 up, 30 down = 150/180 = 83.33%
        self.assertIsNotNone(result.availability_pct)
        self.assertAlmostEqual(result.availability_pct or 0.0, 83.3333, places=2)
        self.assertEqual(result.flap_count, 1)
    
    def test_rolling_window_quality_averages(self):
        """Test quality metric averages in rolling window."""
        records = [
            self._create_quality_record("2024010110", 0.1, 10.0, 50.0),
            self._create_quality_record("2024010111", 0.2, 15.0, 60.0),
            self._create_quality_record("2024010112", 0.3, 20.0, 70.0),
        ]
        
        window_end = datetime(2024, 1, 1, 13, 0, tzinfo=timezone.utc)
        
        result = self.aggregator.calculate_rolling_window(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            utilization_records=[],
            status_records=[],
            quality_records=records,
            window_hours=3,
            window_end=window_end
        )
        
        # Averages: loss=0.2, jitter=15, latency=60
        self.assertIsNotNone(result.loss_avg)
        self.assertIsNotNone(result.jitter_avg)
        self.assertIsNotNone(result.latency_avg)
        self.assertAlmostEqual(result.loss_avg or 0.0, 0.2, places=2)
        self.assertAlmostEqual(result.jitter_avg or 0.0, 15.0, places=1)
        self.assertAlmostEqual(result.latency_avg or 0.0, 60.0, places=1)
    
    def test_calculate_rolling_windows_for_circuit_all_windows(self):
        """Test that all window sizes (3h, 12h, 24h) are calculated."""
        records = [
            self._create_utilization_record(f"2024010{i:02d}", 50.0 + i)
            for i in range(24)
        ]
        
        window_end = datetime(2024, 1, 1, 23, 30, tzinfo=timezone.utc)
        
        results = self.aggregator.calculate_rolling_windows_for_circuit(
            site_id=self.test_site_id,
            circuit_id=self.test_circuit_id,
            utilization_records=records,
            status_records=[],
            quality_records=[],
            window_end=window_end
        )
        
        self.assertIn(3, results)
        self.assertIn(12, results)
        self.assertIn(24, results)
        self.assertEqual(results[3].window_hours, 3)
        self.assertEqual(results[12].window_hours, 12)
        self.assertEqual(results[24].window_hours, 24)
    
    def test_percentile_calculation(self):
        """Test percentile calculation helper."""
        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        
        # P95 should be close to 95
        p95 = self.aggregator._calculate_percentile(values, 95)
        self.assertIsNotNone(p95)
        self.assertAlmostEqual(p95 or 0.0, 95.5, places=1)
        
        # P50 (median) should be 55
        p50 = self.aggregator._calculate_percentile(values, 50)
        self.assertIsNotNone(p50)
        self.assertAlmostEqual(p50 or 0.0, 55.0, places=1)
    
    def test_percentile_empty_list(self):
        """Test percentile returns None for empty list."""
        result = self.aggregator._calculate_percentile([], 95)
        self.assertIsNone(result)
    
    def test_filter_records_in_window(self):
        """Test record filtering by time window."""
        records = [
            self._create_utilization_record("2024010108", 50.0),  # Before window
            self._create_utilization_record("2024010110", 60.0),  # In window
            self._create_utilization_record("2024010111", 70.0),  # In window
            self._create_utilization_record("2024010112", 80.0),  # In window
            self._create_utilization_record("2024010114", 90.0),  # After window
        ]
        
        window_start = datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
        window_end = datetime(2024, 1, 1, 12, 59, tzinfo=timezone.utc)
        
        filtered = self.aggregator._filter_records_in_window(
            records, window_start, window_end
        )
        
        self.assertEqual(len(filtered), 3)
        self.assertEqual(filtered[0].hour_key, "2024010110")
        self.assertEqual(filtered[2].hour_key, "2024010112")


class TestRollingWindowMetricsModel(unittest.TestCase):
    """Test cases for RollingWindowMetrics data model."""
    
    def test_to_dict_contains_all_fields(self):
        """Test that to_dict returns all expected fields."""
        window_end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        
        metrics = RollingWindowMetrics(
            site_id="site-001",
            circuit_id="device:wan0",
            window_end=window_end,
            window_hours=3,
            utilization_avg=75.5,
            utilization_max=92.0,
            continuous_hours_above_70=2.0,
            cumulative_hours_above_80=1.0,
            availability_pct=99.5,
            flap_count=1
        )
        
        result = metrics.to_dict()
        
        self.assertEqual(result["site_id"], "site-001")
        self.assertEqual(result["circuit_id"], "device:wan0")
        self.assertEqual(result["window_hours"], 3)
        self.assertEqual(result["utilization_avg"], 75.5)
        self.assertEqual(result["continuous_hours_above_70"], 2.0)
        self.assertEqual(result["availability_pct"], 99.5)
    
    def test_primary_key_format(self):
        """Test primary key generation."""
        window_end = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        
        metrics = RollingWindowMetrics(
            site_id="site-001",
            circuit_id="device:wan0",
            window_end=window_end,
            window_hours=3
        )
        
        pk = metrics.primary_key
        
        self.assertIn("site-001", pk)
        self.assertIn("device:wan0", pk)
        self.assertIn("3h", pk)


if __name__ == "__main__":
    unittest.main()
