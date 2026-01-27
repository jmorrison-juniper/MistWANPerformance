"""
MistWANPerformance - Threshold Calculator Tests

Unit tests for threshold calculation logic.
"""

import unittest

from src.calculators.threshold_calculator import ThresholdCalculator
from src.utils.config import ThresholdConfig


class TestThresholdCalculator(unittest.TestCase):
    """Test cases for ThresholdCalculator."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.default_config = ThresholdConfig(
            util_warn=70.0,
            util_high=80.0,
            util_critical=90.0
        )
        
        self.region_overrides = {
            "EMEA": {"util_critical": 85.0},
            "APAC": {"util_warn": 65.0, "util_high": 75.0}
        }
        
        self.store_type_overrides = {
            "flagship": {"util_critical": 95.0},
            "warehouse": {"util_warn": 80.0, "util_high": 90.0, "util_critical": 95.0}
        }
        
        self.calculator = ThresholdCalculator(
            default_config=self.default_config,
            region_overrides=self.region_overrides,
            store_type_overrides=self.store_type_overrides
        )
    
    def test_default_utilization_thresholds(self):
        """Test default threshold values."""
        thresholds = self.calculator.get_utilization_thresholds()
        
        self.assertEqual(thresholds["warn"], 70.0)
        self.assertEqual(thresholds["high"], 80.0)
        self.assertEqual(thresholds["critical"], 90.0)
    
    def test_region_override_partial(self):
        """Test region override with partial values."""
        thresholds = self.calculator.get_utilization_thresholds(region="EMEA")
        
        # EMEA only overrides critical
        self.assertEqual(thresholds["warn"], 70.0)  # Default
        self.assertEqual(thresholds["high"], 80.0)  # Default
        self.assertEqual(thresholds["critical"], 85.0)  # Overridden
    
    def test_region_override_full(self):
        """Test region override with multiple values."""
        thresholds = self.calculator.get_utilization_thresholds(region="APAC")
        
        self.assertEqual(thresholds["warn"], 65.0)  # Overridden
        self.assertEqual(thresholds["high"], 75.0)  # Overridden
        self.assertEqual(thresholds["critical"], 90.0)  # Default
    
    def test_store_type_override(self):
        """Test store type override."""
        thresholds = self.calculator.get_utilization_thresholds(store_type="flagship")
        
        self.assertEqual(thresholds["warn"], 70.0)  # Default
        self.assertEqual(thresholds["high"], 80.0)  # Default
        self.assertEqual(thresholds["critical"], 95.0)  # Overridden
    
    def test_store_type_takes_priority_over_region(self):
        """Test that store type overrides take priority over region."""
        thresholds = self.calculator.get_utilization_thresholds(
            region="EMEA",
            store_type="flagship"
        )
        
        # EMEA sets critical to 85, flagship sets to 95
        # Store type should win
        self.assertEqual(thresholds["critical"], 95.0)
    
    def test_unknown_region_uses_defaults(self):
        """Test that unknown region uses default values."""
        thresholds = self.calculator.get_utilization_thresholds(region="UNKNOWN")
        
        self.assertEqual(thresholds["warn"], 70.0)
        self.assertEqual(thresholds["high"], 80.0)
        self.assertEqual(thresholds["critical"], 90.0)
    
    def test_get_severity_normal(self):
        """Test severity determination - normal."""
        thresholds = {"warn": 70.0, "high": 80.0, "critical": 90.0}
        
        severity = self.calculator.get_severity(50.0, thresholds)
        self.assertEqual(severity, "normal")
    
    def test_get_severity_warn(self):
        """Test severity determination - warn."""
        thresholds = {"warn": 70.0, "high": 80.0, "critical": 90.0}
        
        severity = self.calculator.get_severity(75.0, thresholds)
        self.assertEqual(severity, "warn")
    
    def test_get_severity_high(self):
        """Test severity determination - high."""
        thresholds = {"warn": 70.0, "high": 80.0, "critical": 90.0}
        
        severity = self.calculator.get_severity(85.0, thresholds)
        self.assertEqual(severity, "high")
    
    def test_get_severity_critical(self):
        """Test severity determination - critical."""
        thresholds = {"warn": 70.0, "high": 80.0, "critical": 90.0}
        
        severity = self.calculator.get_severity(95.0, thresholds)
        self.assertEqual(severity, "critical")
    
    def test_get_severity_at_threshold(self):
        """Test severity at exact threshold boundary."""
        thresholds = {"warn": 70.0, "high": 80.0, "critical": 90.0}
        
        # At exactly 70, should be warn (>= comparison)
        severity = self.calculator.get_severity(70.0, thresholds)
        self.assertEqual(severity, "warn")
    
    def test_quality_thresholds_loss(self):
        """Test quality thresholds for loss metric."""
        thresholds = self.calculator.get_quality_thresholds("loss")
        
        self.assertEqual(thresholds["warn"], 0.1)
        self.assertEqual(thresholds["high"], 0.5)
        self.assertEqual(thresholds["critical"], 1.0)
    
    def test_quality_thresholds_jitter(self):
        """Test quality thresholds for jitter metric."""
        thresholds = self.calculator.get_quality_thresholds("jitter")
        
        self.assertEqual(thresholds["warn"], 10.0)
        self.assertEqual(thresholds["high"], 30.0)
        self.assertEqual(thresholds["critical"], 50.0)
    
    def test_quality_thresholds_latency(self):
        """Test quality thresholds for latency metric."""
        thresholds = self.calculator.get_quality_thresholds("latency")
        
        self.assertEqual(thresholds["warn"], 50.0)
        self.assertEqual(thresholds["high"], 100.0)
        self.assertEqual(thresholds["critical"], 150.0)
    
    def test_evaluate_circuit_health_all_normal(self):
        """Test circuit health evaluation - all normal."""
        health = self.calculator.evaluate_circuit_health(
            utilization_pct=50.0,
            loss_pct=0.05,
            jitter_ms=5.0,
            latency_ms=30.0
        )
        
        self.assertEqual(health["overall"], "normal")
        self.assertEqual(health["utilization"]["severity"], "normal")
        self.assertEqual(health["loss"]["severity"], "normal")
        self.assertEqual(health["jitter"]["severity"], "normal")
        self.assertEqual(health["latency"]["severity"], "normal")
    
    def test_evaluate_circuit_health_mixed(self):
        """Test circuit health evaluation - mixed severities."""
        health = self.calculator.evaluate_circuit_health(
            utilization_pct=75.0,  # warn
            loss_pct=0.05,          # normal
            jitter_ms=35.0,         # high
            latency_ms=30.0         # normal
        )
        
        # Overall should be worst case: high
        self.assertEqual(health["overall"], "high")
        self.assertEqual(health["utilization"]["severity"], "warn")
        self.assertEqual(health["jitter"]["severity"], "high")
    
    def test_evaluate_circuit_health_with_nulls(self):
        """Test circuit health evaluation with missing metrics."""
        health = self.calculator.evaluate_circuit_health(
            utilization_pct=85.0,
            loss_pct=None,
            jitter_ms=None,
            latency_ms=None
        )
        
        # Should evaluate based on available metrics only
        self.assertEqual(health["overall"], "high")
        self.assertEqual(health["utilization"]["severity"], "high")
        self.assertEqual(health["loss"]["severity"], "unknown")


if __name__ == "__main__":
    unittest.main()
