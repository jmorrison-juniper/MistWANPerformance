"""
MistWANPerformance - KPI Calculator

Computes derived KPIs from collected circuit metrics.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import statistics

from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    AggregatedMetrics
)


logger = logging.getLogger(__name__)


@dataclass
class DailyAggregateInput:
    """
    Input data container for creating daily aggregates.
    
    Groups related parameters to comply with 5-parameter limit.
    """
    site_id: str
    circuit_id: str
    date_key: str
    utilization_records: List[CircuitUtilizationRecord]
    status_records: List[CircuitStatusRecord]
    quality_records: List[CircuitQualityRecord]


@dataclass
class ThresholdConfig:
    """
    Threshold configuration for utilization alerts.
    """
    warn: float = 70.0
    high: float = 80.0
    critical: float = 90.0


class KPICalculator:
    """
    Calculator for derived KPI metrics.
    
    Computes:
    - Availability percentage
    - Time above threshold (continuous and cumulative)
    - Flap rates
    - Quality score aggregates
    """
    
    def __init__(
        self,
        util_threshold_warn: float = 70.0,
        util_threshold_high: float = 80.0,
        util_threshold_critical: float = 90.0
    ):
        """
        Initialize KPI calculator with thresholds.
        
        Args:
            util_threshold_warn: Warning threshold percentage
            util_threshold_high: High utilization threshold percentage
            util_threshold_critical: Critical utilization threshold percentage
        """
        self.thresholds = ThresholdConfig(
            warn=util_threshold_warn,
            high=util_threshold_high,
            critical=util_threshold_critical
        )
        logger.debug("KPICalculator initialized")
    
    # For backward compatibility
    @property
    def util_threshold_warn(self) -> float:
        """Warning threshold percentage."""
        return self.thresholds.warn
    
    @property
    def util_threshold_high(self) -> float:
        """High utilization threshold percentage."""
        return self.thresholds.high
    
    @property
    def util_threshold_critical(self) -> float:
        """Critical utilization threshold percentage."""
        return self.thresholds.critical
    
    def calculate_availability(
        self,
        status_records: List[CircuitStatusRecord]
    ) -> float:
        """
        Calculate availability percentage from status records.
        
        Formula: availability_pct = up_minutes / total_minutes * 100
        
        Args:
            status_records: List of hourly status records
        
        Returns:
            Availability percentage (0-100)
        """
        if not status_records:
            return 100.0  # No data assumes available
        
        total_up = sum(record.up_minutes for record in status_records)
        total_down = sum(record.down_minutes for record in status_records)
        total_minutes = total_up + total_down
        
        if total_minutes == 0:
            return 100.0
        
        availability = (total_up / total_minutes) * 100
        return round(availability, 4)
    
    def calculate_time_above_threshold_cumulative(
        self,
        utilization_records: List[CircuitUtilizationRecord],
        threshold_pct: float
    ) -> int:
        """
        Calculate cumulative hours above threshold.
        
        Args:
            utilization_records: List of hourly utilization records
            threshold_pct: Utilization threshold percentage
        
        Returns:
            Total hours above threshold
        """
        hours_above = sum(
            1 for record in utilization_records 
            if record.is_above_threshold(threshold_pct)
        )
        return hours_above
    
    def calculate_time_above_threshold_continuous(
        self,
        utilization_records: List[CircuitUtilizationRecord],
        threshold_pct: float
    ) -> int:
        """
        Calculate longest consecutive run above threshold.
        
        Args:
            utilization_records: List of hourly utilization records (should be sorted)
            threshold_pct: Utilization threshold percentage
        
        Returns:
            Longest consecutive hours above threshold
        """
        if not utilization_records:
            return 0
        
        # Sort by hour_key to ensure chronological order
        sorted_records = sorted(utilization_records, key=lambda record: record.hour_key)
        
        max_consecutive = 0
        current_consecutive = 0
        
        for record in sorted_records:
            if record.is_above_threshold(threshold_pct):
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0
        
        return max_consecutive
    
    def calculate_flap_rate(
        self,
        status_records: List[CircuitStatusRecord],
        period_hours: int = 24
    ) -> float:
        """
        Calculate flap rate (flaps per hour).
        
        Args:
            status_records: List of status records
            period_hours: Period length in hours
        
        Returns:
            Average flaps per hour
        """
        if not status_records:
            return 0.0
        
        total_flaps = sum(record.flap_count for record in status_records)
        
        if period_hours == 0:
            return 0.0
        
        return round(total_flaps / period_hours, 4)
    
    def aggregate_utilization(
        self,
        utilization_records: List[CircuitUtilizationRecord]
    ) -> Dict[str, Any]:
        """
        Aggregate utilization metrics for a period.
        
        Args:
            utilization_records: List of hourly utilization records
        
        Returns:
            Dictionary with aggregated metrics
        """
        if not utilization_records:
            return self._empty_utilization_aggregate()
        
        values = [record.utilization_pct for record in utilization_records]
        
        return self._compute_utilization_stats(values, utilization_records)
    
    def _empty_utilization_aggregate(self) -> Dict[str, Any]:
        """Return empty utilization aggregate structure."""
        return {
            "utilization_avg": None,
            "utilization_max": None,
            "utilization_p95": None,
            "hours_above_70": 0,
            "hours_above_80": 0,
            "hours_above_90": 0
        }
    
    def _compute_utilization_stats(
        self,
        values: List[float],
        records: List[CircuitUtilizationRecord]
    ) -> Dict[str, Any]:
        """
        Compute utilization statistics from values.
        
        Args:
            values: List of utilization percentages
            records: Original records for threshold calculations
        
        Returns:
            Dictionary with computed statistics
        """
        # Calculate statistics
        util_avg = round(statistics.mean(values), 2)
        util_max = round(max(values), 2)
        
        # Calculate p95
        sorted_values = sorted(values)
        p95_index = int(len(sorted_values) * 0.95)
        util_p95 = round(sorted_values[min(p95_index, len(sorted_values) - 1)], 2)
        
        # Count hours above thresholds
        hours_70 = self.calculate_time_above_threshold_cumulative(records, self.thresholds.warn)
        hours_80 = self.calculate_time_above_threshold_cumulative(records, self.thresholds.high)
        hours_90 = self.calculate_time_above_threshold_cumulative(records, self.thresholds.critical)
        
        return {
            "utilization_avg": util_avg,
            "utilization_max": util_max,
            "utilization_p95": util_p95,
            "hours_above_70": hours_70,
            "hours_above_80": hours_80,
            "hours_above_90": hours_90
        }
    
    def aggregate_quality(
        self,
        quality_records: List[CircuitQualityRecord]
    ) -> Dict[str, Any]:
        """
        Aggregate quality metrics for a period.
        
        Args:
            quality_records: List of hourly quality records
        
        Returns:
            Dictionary with aggregated quality metrics
        """
        if not quality_records:
            return self._empty_quality_aggregate()
        
        return self._compute_quality_stats(quality_records)
    
    def _empty_quality_aggregate(self) -> Dict[str, Any]:
        """Return empty quality aggregate structure."""
        return {
            "loss_avg": None,
            "loss_max": None,
            "jitter_avg": None,
            "jitter_max": None,
            "latency_avg": None,
            "latency_max": None
        }
    
    def _compute_quality_stats(
        self,
        records: List[CircuitQualityRecord]
    ) -> Dict[str, Any]:
        """
        Compute quality statistics from records.
        
        Args:
            records: List of quality records
        
        Returns:
            Dictionary with computed quality statistics
        """
        # Extract non-null values
        loss_values = [record.frame_loss_pct for record in records if record.frame_loss_pct is not None]
        jitter_values = [record.jitter_ms for record in records if record.jitter_ms is not None]
        latency_values = [record.latency_ms for record in records if record.latency_ms is not None]
        
        return {
            "loss_avg": round(statistics.mean(loss_values), 4) if loss_values else None,
            "loss_max": round(max(loss_values), 4) if loss_values else None,
            "jitter_avg": round(statistics.mean(jitter_values), 2) if jitter_values else None,
            "jitter_max": round(max(jitter_values), 2) if jitter_values else None,
            "latency_avg": round(statistics.mean(latency_values), 2) if latency_values else None,
            "latency_max": round(max(latency_values), 2) if latency_values else None
        }
    
    def create_daily_aggregate(
        self,
        aggregate_input: DailyAggregateInput
    ) -> AggregatedMetrics:
        """
        Create daily aggregated metrics for a circuit.
        
        Args:
            aggregate_input: Container with site, circuit, date, and records
        
        Returns:
            AggregatedMetrics for the day
        """
        # Aggregate utilization
        util_agg = self.aggregate_utilization(aggregate_input.utilization_records)
        
        # Aggregate availability
        availability_data = self._compute_availability_data(aggregate_input.status_records)
        
        # Aggregate quality
        quality_agg = self.aggregate_quality(aggregate_input.quality_records)
        
        return self._build_aggregated_metrics(aggregate_input, util_agg, availability_data, quality_agg)
    
    def create_daily_aggregate_from_params(
        self,
        site_id: str,
        circuit_id: str,
        date_key: str,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord]
    ) -> AggregatedMetrics:
        """
        Create daily aggregate using individual parameters (backward compatibility).
        
        Args:
            site_id: Site UUID
            circuit_id: Circuit ID
            date_key: Date in YYYYMMDD format
            utilization_records: Hourly utilization records for the day
            status_records: Hourly status records for the day
            quality_records: Hourly quality records for the day
        
        Returns:
            AggregatedMetrics for the day
        """
        aggregate_input = DailyAggregateInput(
            site_id=site_id,
            circuit_id=circuit_id,
            date_key=date_key,
            utilization_records=utilization_records,
            status_records=status_records,
            quality_records=quality_records
        )
        return self.create_daily_aggregate(aggregate_input)
    
    def _compute_availability_data(
        self,
        status_records: List[CircuitStatusRecord]
    ) -> Dict[str, Any]:
        """
        Compute availability metrics from status records.
        
        Args:
            status_records: List of status records
        
        Returns:
            Dictionary with availability metrics
        """
        total_up = sum(record.up_minutes for record in status_records) if status_records else 0
        total_down = sum(record.down_minutes for record in status_records) if status_records else 0
        total_flaps = sum(record.flap_count for record in status_records) if status_records else 0
        
        availability = None
        if (total_up + total_down) > 0:
            availability = round((total_up / (total_up + total_down)) * 100, 4)
        
        return {
            "total_up": total_up,
            "total_down": total_down,
            "total_flaps": total_flaps,
            "availability": availability
        }
    
    def _build_aggregated_metrics(
        self,
        aggregate_input: DailyAggregateInput,
        util_agg: Dict[str, Any],
        availability_data: Dict[str, Any],
        quality_agg: Dict[str, Any]
    ) -> AggregatedMetrics:
        """
        Build AggregatedMetrics from computed data.
        
        Args:
            aggregate_input: Input container with identifiers
            util_agg: Utilization aggregates
            availability_data: Availability metrics
            quality_agg: Quality aggregates
        
        Returns:
            Complete AggregatedMetrics object
        """
        return AggregatedMetrics(
            site_id=aggregate_input.site_id,
            circuit_id=aggregate_input.circuit_id,
            period_key=aggregate_input.date_key,
            period_type="daily",
            utilization_avg=util_agg["utilization_avg"],
            utilization_max=util_agg["utilization_max"],
            utilization_p95=util_agg["utilization_p95"],
            hours_above_70=util_agg["hours_above_70"],
            hours_above_80=util_agg["hours_above_80"],
            hours_above_90=util_agg["hours_above_90"],
            total_up_minutes=availability_data["total_up"],
            total_down_minutes=availability_data["total_down"],
            availability_pct=availability_data["availability"],
            total_flaps=availability_data["total_flaps"],
            loss_avg=quality_agg["loss_avg"],
            loss_max=quality_agg["loss_max"],
            jitter_avg=quality_agg["jitter_avg"],
            jitter_max=quality_agg["jitter_max"],
            latency_avg=quality_agg["latency_avg"],
            latency_max=quality_agg["latency_max"]
        )
