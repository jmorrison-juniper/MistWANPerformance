"""
MistWANPerformance - KPI Calculator Tests

Unit tests for KPI calculation logic.
"""

import unittest
from datetime import datetime, timezone

from src.calculators.kpi_calculator import KPICalculator
from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord
)


class TestKPICalculator(unittest.TestCase):
    """Test cases for KPICalculator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.calculator = KPICalculator(
            util_threshold_warn=70.0,
            util_threshold_high=80.0,
            util_threshold_critical=90.0
        )
        self.test_site_id = "test-site-001"
        self.test_circuit_id = "test-device:ge-0/0/0"
    
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
    
    def test_calculate_availability_100_percent(self):
        """Test 100% availability calculation."""
        records = [
            self._create_status_record("2024010101", 60, 0, 0),
            self._create_status_record("2024010102", 60, 0, 0),
            self._create_status_record("2024010103", 60, 0, 0),
        ]
        
        availability = self.calculator.calculate_availability(records)
        self.assertEqual(availability, 100.0)
    
    def test_calculate_availability_with_downtime(self):
        """Test availability with downtime."""
        records = [
            self._create_status_record("2024010101", 60, 0, 0),
            self._create_status_record("2024010102", 30, 30, 1),  # 50% this hour
            self._create_status_record("2024010103", 60, 0, 0),
        ]
        
        # Total: 150 up, 30 down = 150/180 = 83.33%
        availability = self.calculator.calculate_availability(records)
        self.assertAlmostEqual(availability, 83.3333, places=2)
    
    def test_calculate_availability_empty_records(self):
        """Test availability with no records returns 100%."""
        availability = self.calculator.calculate_availability([])
        self.assertEqual(availability, 100.0)
    
    def test_time_above_threshold_cumulative(self):
        """Test cumulative hours above threshold."""
        records = [
            self._create_utilization_record("2024010101", 65.0),
            self._create_utilization_record("2024010102", 75.0),  # Above 70
            self._create_utilization_record("2024010103", 85.0),  # Above 70
            self._create_utilization_record("2024010104", 55.0),
            self._create_utilization_record("2024010105", 95.0),  # Above 70
        ]
        
        hours_above = self.calculator.calculate_time_above_threshold_cumulative(
            records, 70.0
        )
        self.assertEqual(hours_above, 3)
    
    def test_time_above_threshold_continuous(self):
        """Test longest consecutive hours above threshold."""
        records = [
            self._create_utilization_record("2024010101", 65.0),
            self._create_utilization_record("2024010102", 75.0),  # Start streak
            self._create_utilization_record("2024010103", 85.0),  # Continue
            self._create_utilization_record("2024010104", 55.0),  # Break
            self._create_utilization_record("2024010105", 95.0),  # New streak
        ]
        
        max_consecutive = self.calculator.calculate_time_above_threshold_continuous(
            records, 70.0
        )
        self.assertEqual(max_consecutive, 2)  # Longest streak is 2 hours
    
    def test_time_above_threshold_continuous_all_above(self):
        """Test continuous threshold when all hours are above."""
        records = [
            self._create_utilization_record("2024010101", 75.0),
            self._create_utilization_record("2024010102", 85.0),
            self._create_utilization_record("2024010103", 95.0),
        ]
        
        max_consecutive = self.calculator.calculate_time_above_threshold_continuous(
            records, 70.0
        )
        self.assertEqual(max_consecutive, 3)
    
    def test_calculate_flap_rate(self):
        """Test flap rate calculation."""
        records = [
            self._create_status_record("2024010101", 58, 2, 2),
            self._create_status_record("2024010102", 55, 5, 3),
            self._create_status_record("2024010103", 60, 0, 1),
        ]
        
        flap_rate = self.calculator.calculate_flap_rate(records, period_hours=3)
        # Total flaps: 6, over 3 hours = 2.0 flaps/hour
        self.assertEqual(flap_rate, 2.0)
    
    def test_aggregate_utilization(self):
        """Test utilization aggregation."""
        records = [
            self._create_utilization_record("2024010101", 50.0),
            self._create_utilization_record("2024010102", 75.0),
            self._create_utilization_record("2024010103", 85.0),
            self._create_utilization_record("2024010104", 95.0),
        ]
        
        agg = self.calculator.aggregate_utilization(records)
        
        self.assertEqual(agg["utilization_max"], 95.0)
        self.assertAlmostEqual(agg["utilization_avg"], 76.25, places=2)
        self.assertEqual(agg["hours_above_70"], 3)
        self.assertEqual(agg["hours_above_80"], 2)
        self.assertEqual(agg["hours_above_90"], 1)
    
    def test_aggregate_utilization_empty(self):
        """Test utilization aggregation with no records."""
        agg = self.calculator.aggregate_utilization([])
        
        self.assertIsNone(agg["utilization_avg"])
        self.assertIsNone(agg["utilization_max"])
        self.assertEqual(agg["hours_above_70"], 0)


class TestCircuitUtilizationRecord(unittest.TestCase):
    """Test cases for CircuitUtilizationRecord."""
    
    def test_is_above_threshold(self):
        """Test threshold comparison."""
        record = CircuitUtilizationRecord(
            site_id="test",
            circuit_id="test:port",
            hour_key="2024010101",
            utilization_pct=75.0,
            rx_bytes=1000,
            tx_bytes=500,
            bandwidth_mbps=100
        )
        
        self.assertTrue(record.is_above_threshold(70.0))
        self.assertFalse(record.is_above_threshold(80.0))
    
    def test_primary_key(self):
        """Test primary key generation."""
        record = CircuitUtilizationRecord(
            site_id="site-001",
            circuit_id="device:port",
            hour_key="2024010112",
            utilization_pct=50.0,
            rx_bytes=1000,
            tx_bytes=500,
            bandwidth_mbps=100
        )
        
        self.assertEqual(record.primary_key, "site-001|device:port|2024010112")


class TestCircuitStatusRecord(unittest.TestCase):
    """Test cases for CircuitStatusRecord."""
    
    def test_availability_pct(self):
        """Test availability percentage calculation."""
        record = CircuitStatusRecord(
            site_id="test",
            circuit_id="test:port",
            hour_key="2024010101",
            status_code=1,
            up_minutes=45,
            down_minutes=15,
            flap_count=2
        )
        
        self.assertEqual(record.availability_pct, 75.0)
    
    def test_status_hourly(self):
        """Test hourly status string."""
        record_up = CircuitStatusRecord(
            site_id="test",
            circuit_id="test:port",
            hour_key="2024010101",
            status_code=1,
            up_minutes=30,
            down_minutes=30,
            flap_count=1
        )
        
        record_down = CircuitStatusRecord(
            site_id="test",
            circuit_id="test:port",
            hour_key="2024010101",
            status_code=0,
            up_minutes=0,
            down_minutes=60,
            flap_count=0
        )
        
        self.assertEqual(record_up.status_hourly, "Up")
        self.assertEqual(record_down.status_hourly, "Down")


if __name__ == "__main__":
    unittest.main()
