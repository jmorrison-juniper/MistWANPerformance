"""
MistWANPerformance - KPI Calculator

Computes derived KPIs from collected circuit metrics.
"""

import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
import statistics

from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    AggregatedMetrics
)


logger = logging.getLogger(__name__)

# CPU count for parallel processing
CPU_COUNT = min(os.cpu_count() or 4, 8)


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


def _calculate_availability_worker(
    status_records_data: List[Dict[str, Any]]
) -> float:
    """
    Worker function for parallel availability calculation.
    
    Accepts serializable dict data to avoid pickling issues with dataclasses.
    
    Args:
        status_records_data: List of status record dictionaries
    
    Returns:
        Availability percentage (0-100)
    """
    if not status_records_data:
        return 100.0
    
    total_up = sum(record.get("up_minutes", 0) for record in status_records_data)
    total_down = sum(record.get("down_minutes", 0) for record in status_records_data)
    total_minutes = total_up + total_down
    
    if total_minutes == 0:
        return 100.0
    
    availability = (total_up / total_minutes) * 100
    return round(availability, 4)


def _create_daily_aggregate_worker(
    worker_input: Tuple[str, str, str, List[Dict], List[Dict], List[Dict], Dict[str, float]]
) -> Dict[str, Any]:
    """
    Worker function for parallel daily aggregate creation.
    
    Accepts serializable data to avoid pickling issues.
    
    Args:
        worker_input: Tuple of (site_id, circuit_id, date_key, 
                               util_records_data, status_records_data, 
                               quality_records_data, thresholds)
    
    Returns:
        Dictionary representation of AggregatedMetrics
    """
    site_id, circuit_id, date_key, util_data, status_data, quality_data, thresholds = worker_input
    
    # Calculate utilization aggregates
    util_agg = _aggregate_utilization_data(util_data, thresholds)
    
    # Calculate availability
    availability_data = _compute_availability_from_data(status_data)
    
    # Calculate quality aggregates
    quality_agg = _aggregate_quality_data(quality_data)
    
    return {
        "site_id": site_id,
        "circuit_id": circuit_id,
        "period_key": date_key,
        "period_type": "daily",
        "utilization_avg": util_agg["utilization_avg"],
        "utilization_max": util_agg["utilization_max"],
        "utilization_p95": util_agg["utilization_p95"],
        "hours_above_70": util_agg["hours_above_70"],
        "hours_above_80": util_agg["hours_above_80"],
        "hours_above_90": util_agg["hours_above_90"],
        "total_up_minutes": availability_data["total_up"],
        "total_down_minutes": availability_data["total_down"],
        "availability_pct": availability_data["availability"],
        "total_flaps": availability_data["total_flaps"],
        "loss_avg": quality_agg["loss_avg"],
        "loss_max": quality_agg["loss_max"],
        "jitter_avg": quality_agg["jitter_avg"],
        "jitter_max": quality_agg["jitter_max"],
        "latency_avg": quality_agg["latency_avg"],
        "latency_max": quality_agg["latency_max"]
    }


def _aggregate_utilization_data(
    util_data: List[Dict[str, Any]],
    thresholds: Dict[str, float]
) -> Dict[str, Any]:
    """Aggregate utilization from raw data dictionaries."""
    if not util_data:
        return {
            "utilization_avg": None,
            "utilization_max": None,
            "utilization_p95": None,
            "hours_above_70": 0,
            "hours_above_80": 0,
            "hours_above_90": 0
        }
    
    values = [record.get("utilization_pct", 0.0) for record in util_data]
    
    util_avg = round(statistics.mean(values), 2)
    util_max = round(max(values), 2)
    
    sorted_values = sorted(values)
    p95_index = int(len(sorted_values) * 0.95)
    util_p95 = round(sorted_values[min(p95_index, len(sorted_values) - 1)], 2)
    
    warn_threshold = thresholds.get("warn", 70.0)
    high_threshold = thresholds.get("high", 80.0)
    critical_threshold = thresholds.get("critical", 90.0)
    
    hours_70 = sum(1 for val in values if val >= warn_threshold)
    hours_80 = sum(1 for val in values if val >= high_threshold)
    hours_90 = sum(1 for val in values if val >= critical_threshold)
    
    return {
        "utilization_avg": util_avg,
        "utilization_max": util_max,
        "utilization_p95": util_p95,
        "hours_above_70": hours_70,
        "hours_above_80": hours_80,
        "hours_above_90": hours_90
    }


def _compute_availability_from_data(
    status_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Compute availability metrics from status data dictionaries."""
    total_up = sum(record.get("up_minutes", 0) for record in status_data) if status_data else 0
    total_down = sum(record.get("down_minutes", 0) for record in status_data) if status_data else 0
    total_flaps = sum(record.get("flap_count", 0) for record in status_data) if status_data else 0
    
    availability = None
    if (total_up + total_down) > 0:
        availability = round((total_up / (total_up + total_down)) * 100, 4)
    
    return {
        "total_up": total_up,
        "total_down": total_down,
        "total_flaps": total_flaps,
        "availability": availability
    }


def _aggregate_quality_data(
    quality_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Aggregate quality metrics from raw data dictionaries."""
    if not quality_data:
        return {
            "loss_avg": None,
            "loss_max": None,
            "jitter_avg": None,
            "jitter_max": None,
            "latency_avg": None,
            "latency_max": None
        }
    
    loss_values = [record.get("frame_loss_pct") for record in quality_data if record.get("frame_loss_pct") is not None]
    jitter_values = [record.get("jitter_ms") for record in quality_data if record.get("jitter_ms") is not None]
    latency_values = [record.get("latency_ms") for record in quality_data if record.get("latency_ms") is not None]
    
    return {
        "loss_avg": round(statistics.mean(loss_values), 4) if loss_values else None,
        "loss_max": round(max(loss_values), 4) if loss_values else None,
        "jitter_avg": round(statistics.mean(jitter_values), 2) if jitter_values else None,
        "jitter_max": round(max(jitter_values), 2) if jitter_values else None,
        "latency_avg": round(statistics.mean(latency_values), 2) if latency_values else None,
        "latency_max": round(max(latency_values), 2) if latency_values else None
    }


def calculate_availability_bulk(
    circuit_status_map: Dict[str, List[CircuitStatusRecord]],
    use_parallel: bool = True
) -> Dict[str, float]:
    """
    Calculate availability for multiple circuits in parallel.
    
    Args:
        circuit_status_map: Dictionary mapping circuit_id to status records
        use_parallel: Whether to use ProcessPoolExecutor (default True)
    
    Returns:
        Dictionary mapping circuit_id to availability percentage
    """
    if not circuit_status_map:
        return {}
    
    # Convert dataclasses to dicts for pickling
    circuit_data = {
        circuit_id: [
            {"up_minutes": record.up_minutes, "down_minutes": record.down_minutes}
            for record in records
        ]
        for circuit_id, records in circuit_status_map.items()
    }
    
    results = {}
    
    if use_parallel and len(circuit_data) > 10:
        logger.info(f"[...] Calculating availability for {len(circuit_data)} circuits in parallel")
        
        with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
            futures = {
                executor.submit(_calculate_availability_worker, data): circuit_id
                for circuit_id, data in circuit_data.items()
            }
            
            for future in as_completed(futures):
                circuit_id = futures[future]
                try:
                    results[circuit_id] = future.result()
                except Exception as error:
                    logger.error(f"Error calculating availability for {circuit_id}: {error}")
                    results[circuit_id] = 100.0
    else:
        # Single-threaded for small datasets
        for circuit_id, data in circuit_data.items():
            results[circuit_id] = _calculate_availability_worker(data)
    
    return results


def create_daily_aggregates_parallel(
    aggregate_inputs: List[DailyAggregateInput],
    thresholds: ThresholdConfig,
    use_parallel: bool = True
) -> List[AggregatedMetrics]:
    """
    Create daily aggregates for multiple circuits in parallel.
    
    Args:
        aggregate_inputs: List of DailyAggregateInput objects
        thresholds: Threshold configuration
        use_parallel: Whether to use ProcessPoolExecutor (default True)
    
    Returns:
        List of AggregatedMetrics objects
    """
    if not aggregate_inputs:
        return []
    
    # Convert to serializable format
    threshold_dict = {
        "warn": thresholds.warn,
        "high": thresholds.high,
        "critical": thresholds.critical
    }
    
    worker_inputs = []
    for inp in aggregate_inputs:
        util_data = [
            {
                "utilization_pct": record.utilization_pct,
                "rx_bytes": record.rx_bytes,
                "tx_bytes": record.tx_bytes
            }
            for record in inp.utilization_records
        ]
        status_data = [
            {
                "up_minutes": record.up_minutes,
                "down_minutes": record.down_minutes,
                "flap_count": record.flap_count
            }
            for record in inp.status_records
        ]
        quality_data = [
            {
                "frame_loss_pct": record.frame_loss_pct,
                "jitter_ms": record.jitter_ms,
                "latency_ms": record.latency_ms
            }
            for record in inp.quality_records
        ]
        worker_inputs.append((
            inp.site_id,
            inp.circuit_id,
            inp.date_key,
            util_data,
            status_data,
            quality_data,
            threshold_dict
        ))
    
    results = []
    
    if use_parallel and len(worker_inputs) > 10:
        logger.info(f"[...] Creating daily aggregates for {len(worker_inputs)} circuits in parallel")
        
        with ProcessPoolExecutor(max_workers=CPU_COUNT) as executor:
            futures = [
                executor.submit(_create_daily_aggregate_worker, inp)
                for inp in worker_inputs
            ]
            
            for future in as_completed(futures):
                try:
                    result_dict = future.result()
                    results.append(AggregatedMetrics(**result_dict))
                except Exception as error:
                    logger.error(f"Error creating daily aggregate: {error}")
    else:
        # Single-threaded for small datasets
        for inp in worker_inputs:
            try:
                result_dict = _create_daily_aggregate_worker(inp)
                results.append(AggregatedMetrics(**result_dict))
            except Exception as error:
                logger.error(f"Error creating daily aggregate: {error}")
    
    logger.info(f"[OK] Created {len(results)} daily aggregates")
    return results