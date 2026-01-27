"""
MistWANPerformance - Time Aggregator

Handles time-based rollups from hourly to daily/weekly/monthly.
Organized per 5-item rule into focused classes.
"""

import logging
import statistics
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict

from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    AggregatedMetrics,
    RollingWindowMetrics
)
from src.calculators.kpi_calculator import KPICalculator


logger = logging.getLogger(__name__)


class AggregateCalculator:
    """
    Helper class for aggregate calculation operations.
    
    Provides shared calculation methods for aggregators.
    """
    
    @staticmethod
    def calculate_percentile(values: List[float], percentile: int) -> Optional[float]:
        """
        Calculate percentile value from a list.
        
        Args:
            values: List of numeric values
            percentile: Percentile to calculate (0-100)
        
        Returns:
            Percentile value or None if empty
        """
        if not values:
            return None
        
        sorted_values = sorted(values)
        index = (len(sorted_values) - 1) * percentile / 100
        lower = int(index)
        upper = lower + 1
        
        if upper >= len(sorted_values):
            return sorted_values[-1]
        
        weight = index - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    
    @staticmethod
    def merge_aggregates(
        site_id: str,
        circuit_id: Optional[str],
        period_key: str,
        period_type: str,
        aggregates: List[AggregatedMetrics]
    ) -> AggregatedMetrics:
        """
        Merge multiple aggregates into a single summary.
        
        Args:
            site_id: Site UUID or region name
            circuit_id: Circuit ID (None for region level)
            period_key: Period identifier
            period_type: "weekly" or "monthly"
            aggregates: List of aggregates to merge
        
        Returns:
            Merged AggregatedMetrics
        """
        if not aggregates:
            return AggregatedMetrics(
                site_id=site_id,
                circuit_id=circuit_id,
                period_key=period_key,
                period_type=period_type
            )
        
        # Collect non-null values for averaging
        metrics = AggregateCalculator._collect_aggregate_metrics(aggregates)
        totals = AggregateCalculator._sum_aggregate_totals(aggregates)
        
        # Calculate availability
        availability = None
        total_minutes = totals["up"] + totals["down"]
        if total_minutes > 0:
            availability = round((totals["up"] / total_minutes) * 100, 4)
        
        return AggregatedMetrics(
            site_id=site_id,
            circuit_id=circuit_id,
            period_key=period_key,
            period_type=period_type,
            utilization_avg=round(statistics.mean(metrics["util_avgs"]), 2) if metrics["util_avgs"] else None,
            utilization_max=round(max(metrics["util_maxes"]), 2) if metrics["util_maxes"] else None,
            utilization_p95=round(max(metrics["util_p95s"]), 2) if metrics["util_p95s"] else None,
            hours_above_70=totals["hours_70"],
            hours_above_80=totals["hours_80"],
            hours_above_90=totals["hours_90"],
            total_up_minutes=totals["up"],
            total_down_minutes=totals["down"],
            availability_pct=availability,
            total_flaps=totals["flaps"],
            loss_avg=round(statistics.mean(metrics["loss_avgs"]), 4) if metrics["loss_avgs"] else None,
            loss_max=round(max(metrics["loss_maxes"]), 4) if metrics["loss_maxes"] else None,
            jitter_avg=round(statistics.mean(metrics["jitter_avgs"]), 2) if metrics["jitter_avgs"] else None,
            jitter_max=round(max(metrics["jitter_maxes"]), 2) if metrics["jitter_maxes"] else None,
            latency_avg=round(statistics.mean(metrics["latency_avgs"]), 2) if metrics["latency_avgs"] else None,
            latency_max=round(max(metrics["latency_maxes"]), 2) if metrics["latency_maxes"] else None
        )
    
    @staticmethod
    def _collect_aggregate_metrics(aggregates: List[AggregatedMetrics]) -> Dict[str, List[float]]:
        """Collect non-null metric values from aggregates."""
        return {
            "util_avgs": [a.utilization_avg for a in aggregates if a.utilization_avg is not None],
            "util_maxes": [a.utilization_max for a in aggregates if a.utilization_max is not None],
            "util_p95s": [a.utilization_p95 for a in aggregates if a.utilization_p95 is not None],
            "loss_avgs": [a.loss_avg for a in aggregates if a.loss_avg is not None],
            "loss_maxes": [a.loss_max for a in aggregates if a.loss_max is not None],
            "jitter_avgs": [a.jitter_avg for a in aggregates if a.jitter_avg is not None],
            "jitter_maxes": [a.jitter_max for a in aggregates if a.jitter_max is not None],
            "latency_avgs": [a.latency_avg for a in aggregates if a.latency_avg is not None],
            "latency_maxes": [a.latency_max for a in aggregates if a.latency_max is not None]
        }
    
    @staticmethod
    def _sum_aggregate_totals(aggregates: List[AggregatedMetrics]) -> Dict[str, int]:
        """Sum total counts from aggregates."""
        return {
            "up": sum(a.total_up_minutes for a in aggregates),
            "down": sum(a.total_down_minutes for a in aggregates),
            "flaps": sum(a.total_flaps for a in aggregates),
            "hours_70": sum(a.hours_above_70 for a in aggregates),
            "hours_80": sum(a.hours_above_80 for a in aggregates),
            "hours_90": sum(a.hours_above_90 for a in aggregates)
        }


class CalendarAggregator:
    """
    Handles calendar-based aggregations.
    
    Handles:
    - Hourly to daily rollups
    - Daily to weekly rollups
    - Daily to monthly rollups
    """
    
    def __init__(self, kpi_calculator: Optional[KPICalculator] = None):
        """
        Initialize the calendar aggregator.
        
        Args:
            kpi_calculator: KPI calculator instance (creates default if None)
        """
        self.kpi_calculator = kpi_calculator or KPICalculator()
        logger.debug("CalendarAggregator initialized")
    
    def aggregate_hourly_to_daily(
        self,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord]
    ) -> List[AggregatedMetrics]:
        """
        Aggregate hourly records to daily summaries.
        
        Args:
            utilization_records: Hourly utilization records
            status_records: Hourly status records
            quality_records: Hourly quality records
        
        Returns:
            List of daily AggregatedMetrics
        """
        logger.info("[...] Aggregating hourly data to daily")
        
        # Group records by circuit and date
        util_grouped = self._group_by_circuit_date(utilization_records)
        status_grouped = self._group_by_circuit_date(status_records)
        quality_grouped = self._group_by_circuit_date(quality_records)
        
        # Find all unique (site_id, circuit_id, date) combinations
        all_keys = set(util_grouped.keys()) | set(status_grouped.keys()) | set(quality_grouped.keys())
        
        daily_aggregates = []
        
        for site_id, circuit_id, date_key in all_keys:
            key = (site_id, circuit_id, date_key)
            
            daily_agg = self.kpi_calculator.create_daily_aggregate_from_params(
                site_id=site_id,
                circuit_id=circuit_id,
                date_key=date_key,
                utilization_records=util_grouped.get(key, []),
                status_records=status_grouped.get(key, []),
                quality_records=quality_grouped.get(key, [])
            )
            daily_aggregates.append(daily_agg)
        
        logger.info(f"[OK] Created {len(daily_aggregates)} daily aggregates")
        return daily_aggregates
    
    def aggregate_daily_to_weekly(
        self,
        daily_aggregates: List[AggregatedMetrics]
    ) -> List[AggregatedMetrics]:
        """
        Aggregate daily records to weekly summaries.
        
        Args:
            daily_aggregates: Daily aggregated metrics
        
        Returns:
            List of weekly AggregatedMetrics
        """
        logger.info("[...] Aggregating daily data to weekly")
        
        grouped = defaultdict(list)
        
        for aggregate in daily_aggregates:
            week_key = self._get_week_key(aggregate.period_key)
            key = (aggregate.site_id, aggregate.circuit_id, week_key)
            grouped[key].append(aggregate)
        
        weekly_aggregates = []
        
        for (site_id, circuit_id, week_key), daily_records in grouped.items():
            weekly_agg = AggregateCalculator.merge_aggregates(
                site_id, circuit_id, week_key, "weekly", daily_records
            )
            weekly_aggregates.append(weekly_agg)
        
        logger.info(f"[OK] Created {len(weekly_aggregates)} weekly aggregates")
        return weekly_aggregates
    
    def aggregate_daily_to_monthly(
        self,
        daily_aggregates: List[AggregatedMetrics]
    ) -> List[AggregatedMetrics]:
        """
        Aggregate daily records to monthly summaries.
        
        Args:
            daily_aggregates: Daily aggregated metrics
        
        Returns:
            List of monthly AggregatedMetrics
        """
        logger.info("[...] Aggregating daily data to monthly")
        
        grouped = defaultdict(list)
        
        for aggregate in daily_aggregates:
            month_key = self._get_month_key(aggregate.period_key)
            key = (aggregate.site_id, aggregate.circuit_id, month_key)
            grouped[key].append(aggregate)
        
        monthly_aggregates = []
        
        for (site_id, circuit_id, month_key), daily_records in grouped.items():
            monthly_agg = AggregateCalculator.merge_aggregates(
                site_id, circuit_id, month_key, "monthly", daily_records
            )
            monthly_aggregates.append(monthly_agg)
        
        logger.info(f"[OK] Created {len(monthly_aggregates)} monthly aggregates")
        return monthly_aggregates
    
    def _group_by_circuit_date(
        self,
        records: List[Any]
    ) -> Dict[Tuple[str, str, str], List[Any]]:
        """Group records by site_id, circuit_id, and date."""
        grouped = defaultdict(list)
        
        for record in records:
            date_key = record.hour_key[:8]
            key = (record.site_id, record.circuit_id, date_key)
            grouped[key].append(record)
        
        return dict(grouped)
    
    def _get_week_key(self, date_key: str) -> str:
        """Get ISO week key (YYYYWW) from date key (YYYYMMDD)."""
        parsed_date = datetime.strptime(date_key, "%Y%m%d")
        iso_year, iso_week, _ = parsed_date.isocalendar()
        return f"{iso_year}{iso_week:02d}"
    
    def _get_month_key(self, date_key: str) -> str:
        """Get month key (YYYYMM) from date key (YYYYMMDD)."""
        return date_key[:6]


class RollingWindowAggregator:
    """
    Handles rolling time window aggregations.
    
    Handles:
    - 3-hour rolling windows
    - 12-hour rolling windows
    - 24-hour rolling windows
    """
    
    def __init__(self):
        """Initialize the rolling window aggregator."""
        logger.debug("RollingWindowAggregator initialized")
    
    def calculate_rolling_window(
        self,
        site_id: str,
        circuit_id: str,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord],
        window_hours: int,
        window_end: Optional[datetime] = None
    ) -> RollingWindowMetrics:
        """
        Calculate metrics for a rolling time window.
        
        Args:
            site_id: Site UUID
            circuit_id: Circuit identifier
            utilization_records: Hourly utilization records
            status_records: Hourly status records  
            quality_records: Hourly quality records
            window_hours: Window size (3, 12, or 24)
            window_end: End of window (default: now)
        
        Returns:
            RollingWindowMetrics for the window
        """
        if window_end is None:
            window_end = datetime.now(timezone.utc)
        
        window_start = window_end - timedelta(hours=window_hours)
        
        # Filter records within window
        util_in_window = self._filter_records_in_window(
            utilization_records, window_start, window_end
        )
        status_in_window = self._filter_records_in_window(
            status_records, window_start, window_end
        )
        quality_in_window = self._filter_records_in_window(
            quality_records, window_start, window_end
        )
        
        # Calculate all metrics
        util_metrics = self._calculate_utilization_metrics(util_in_window)
        avail_metrics = self._calculate_availability_metrics(status_in_window)
        quality_metrics = self._calculate_quality_metrics(quality_in_window)
        
        return RollingWindowMetrics(
            site_id=site_id,
            circuit_id=circuit_id,
            window_end=window_end,
            window_hours=window_hours,
            utilization_avg=util_metrics["avg"],
            utilization_max=util_metrics["max"],
            utilization_p95=util_metrics["p95"],
            continuous_hours_above_70=util_metrics["continuous_70"],
            continuous_hours_above_80=util_metrics["continuous_80"],
            continuous_hours_above_90=util_metrics["continuous_90"],
            cumulative_hours_above_70=util_metrics["cumulative_70"],
            cumulative_hours_above_80=util_metrics["cumulative_80"],
            cumulative_hours_above_90=util_metrics["cumulative_90"],
            availability_pct=avail_metrics["availability"],
            flap_count=avail_metrics["flaps"],
            loss_avg=quality_metrics["loss"],
            jitter_avg=quality_metrics["jitter"],
            latency_avg=quality_metrics["latency"]
        )
    
    def calculate_all_windows(
        self,
        site_id: str,
        circuit_id: str,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord],
        window_end: Optional[datetime] = None
    ) -> Dict[int, RollingWindowMetrics]:
        """
        Calculate all rolling windows (3h, 12h, 24h) for a circuit.
        
        Args:
            site_id: Site UUID
            circuit_id: Circuit identifier
            utilization_records: Hourly utilization records
            status_records: Hourly status records
            quality_records: Hourly quality records
            window_end: End of windows (default: now)
        
        Returns:
            Dictionary mapping window_hours to RollingWindowMetrics
        """
        results = {}
        
        for window_hours in [3, 12, 24]:
            results[window_hours] = self.calculate_rolling_window(
                site_id=site_id,
                circuit_id=circuit_id,
                utilization_records=utilization_records,
                status_records=status_records,
                quality_records=quality_records,
                window_hours=window_hours,
                window_end=window_end
            )
        
        return results
    
    def _filter_records_in_window(
        self,
        records: List[Any],
        window_start: datetime,
        window_end: datetime
    ) -> List[Any]:
        """Filter records that fall within the time window."""
        start_key = window_start.strftime("%Y%m%d%H")
        end_key = window_end.strftime("%Y%m%d%H")
        return [record for record in records if start_key <= record.hour_key <= end_key]
    
    def _calculate_utilization_metrics(
        self,
        records: List[CircuitUtilizationRecord]
    ) -> Dict[str, Any]:
        """Calculate utilization metrics from records."""
        if not records:
            return {
                "avg": None, "max": None, "p95": None,
                "continuous_70": 0.0, "continuous_80": 0.0, "continuous_90": 0.0,
                "cumulative_70": 0.0, "cumulative_80": 0.0, "cumulative_90": 0.0
            }
        
        values = [record.utilization_pct for record in records]
        p95_value = AggregateCalculator.calculate_percentile(values, 95)
        
        return {
            "avg": round(statistics.mean(values), 2) if values else None,
            "max": round(max(values), 2) if values else None,
            "p95": round(p95_value, 2) if p95_value else None,
            "continuous_70": self._calculate_continuous_hours(records, 70.0),
            "continuous_80": self._calculate_continuous_hours(records, 80.0),
            "continuous_90": self._calculate_continuous_hours(records, 90.0),
            "cumulative_70": self._calculate_cumulative_hours(records, 70.0),
            "cumulative_80": self._calculate_cumulative_hours(records, 80.0),
            "cumulative_90": self._calculate_cumulative_hours(records, 90.0)
        }
    
    def _calculate_availability_metrics(
        self,
        records: List[CircuitStatusRecord]
    ) -> Dict[str, Any]:
        """Calculate availability metrics from records."""
        total_up = sum(record.up_minutes for record in records)
        total_down = sum(record.down_minutes for record in records)
        total_flaps = sum(record.flap_count for record in records)
        
        availability = None
        total_minutes = total_up + total_down
        if total_minutes > 0:
            availability = round((total_up / total_minutes) * 100, 4)
        
        return {"availability": availability, "flaps": total_flaps}
    
    def _calculate_quality_metrics(
        self,
        records: List[CircuitQualityRecord]
    ) -> Dict[str, Optional[float]]:
        """Calculate quality metrics from records."""
        loss_values = [record.loss_avg for record in records if record.loss_avg is not None]
        jitter_values = [record.jitter_avg for record in records if record.jitter_avg is not None]
        latency_values = [record.latency_avg for record in records if record.latency_avg is not None]
        
        return {
            "loss": round(statistics.mean(loss_values), 4) if loss_values else None,
            "jitter": round(statistics.mean(jitter_values), 2) if jitter_values else None,
            "latency": round(statistics.mean(latency_values), 2) if latency_values else None
        }
    
    def _calculate_continuous_hours(
        self,
        records: List[CircuitUtilizationRecord],
        threshold: float
    ) -> float:
        """Calculate longest continuous run above threshold."""
        if not records:
            return 0.0
        
        sorted_records = sorted(records, key=lambda record: record.hour_key)
        max_run = 0
        current_run = 0
        
        for record in sorted_records:
            if record.utilization_pct >= threshold:
                current_run += 1
                max_run = max(max_run, current_run)
            else:
                current_run = 0
        
        return float(max_run)
    
    def _calculate_cumulative_hours(
        self,
        records: List[CircuitUtilizationRecord],
        threshold: float
    ) -> float:
        """Calculate total hours above threshold."""
        if not records:
            return 0.0
        return float(sum(1 for record in records if record.utilization_pct >= threshold))


class RegionAggregator:
    """
    Handles region-level aggregations.
    
    Aggregates circuit metrics to geographic regions.
    """
    
    def __init__(self):
        """Initialize the region aggregator."""
        logger.debug("RegionAggregator initialized")
    
    def aggregate_to_region(
        self,
        aggregates: List[AggregatedMetrics],
        site_region_map: Dict[str, str]
    ) -> List[AggregatedMetrics]:
        """
        Aggregate circuit metrics to region level.
        
        Args:
            aggregates: Circuit-level aggregates
            site_region_map: Mapping of site_id to region
        
        Returns:
            List of region-level AggregatedMetrics
        """
        logger.info("[...] Aggregating to region level")
        
        grouped = defaultdict(list)
        
        for aggregate in aggregates:
            region = site_region_map.get(aggregate.site_id, "Unknown")
            key = (region, aggregate.period_key, aggregate.period_type)
            grouped[key].append(aggregate)
        
        region_aggregates = []
        
        for (region, period_key, period_type), circuit_aggs in grouped.items():
            region_agg = AggregateCalculator.merge_aggregates(
                site_id=region,
                circuit_id=None,
                period_key=period_key,
                period_type=period_type,
                aggregates=circuit_aggs
            )
            region_aggregates.append(region_agg)
        
        logger.info(f"[OK] Created {len(region_aggregates)} region aggregates")
        return region_aggregates


class TimeAggregator:
    """
    Facade class for time-based aggregation operations.
    
    Provides unified interface to CalendarAggregator, 
    RollingWindowAggregator, and RegionAggregator.
    """
    
    def __init__(self, kpi_calculator: Optional[KPICalculator] = None):
        """
        Initialize the time aggregator facade.
        
        Args:
            kpi_calculator: KPI calculator instance (creates default if None)
        """
        self.calendar = CalendarAggregator(kpi_calculator)
        self.rolling = RollingWindowAggregator()
        self.region = RegionAggregator()
        logger.debug("TimeAggregator initialized")
    
    def aggregate_hourly_to_daily(
        self,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord]
    ) -> List[AggregatedMetrics]:
        """Aggregate hourly records to daily summaries."""
        return self.calendar.aggregate_hourly_to_daily(
            utilization_records, status_records, quality_records
        )
    
    def aggregate_daily_to_weekly(
        self,
        daily_aggregates: List[AggregatedMetrics]
    ) -> List[AggregatedMetrics]:
        """Aggregate daily records to weekly summaries."""
        return self.calendar.aggregate_daily_to_weekly(daily_aggregates)
    
    def aggregate_daily_to_monthly(
        self,
        daily_aggregates: List[AggregatedMetrics]
    ) -> List[AggregatedMetrics]:
        """Aggregate daily records to monthly summaries."""
        return self.calendar.aggregate_daily_to_monthly(daily_aggregates)
    
    def aggregate_to_region(
        self,
        aggregates: List[AggregatedMetrics],
        site_region_map: Dict[str, str]
    ) -> List[AggregatedMetrics]:
        """Aggregate circuit metrics to region level."""
        return self.region.aggregate_to_region(aggregates, site_region_map)
    
    def calculate_rolling_window(
        self,
        site_id: str,
        circuit_id: str,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord],
        window_hours: int,
        window_end: Optional[datetime] = None
    ) -> RollingWindowMetrics:
        """Calculate metrics for a rolling time window."""
        return self.rolling.calculate_rolling_window(
            site_id, circuit_id, utilization_records,
            status_records, quality_records, window_hours, window_end
        )
    
    def calculate_rolling_windows_for_circuit(
        self,
        site_id: str,
        circuit_id: str,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord],
        window_end: Optional[datetime] = None
    ) -> Dict[int, RollingWindowMetrics]:
        """Calculate all rolling windows (3h, 12h, 24h) for a circuit."""
        return self.rolling.calculate_all_windows(
            site_id, circuit_id, utilization_records,
            status_records, quality_records, window_end
        )
    
    # Helper method proxies for backward compatibility with tests
    
    def _calculate_percentile(self, values: List[float], percentile: int) -> Optional[float]:
        """Proxy to AggregateCalculator.calculate_percentile for backward compatibility."""
        return AggregateCalculator.calculate_percentile(values, percentile)
    
    def _filter_records_in_window(
        self,
        records: List[Any],
        window_start: datetime,
        window_end: datetime
    ) -> List[Any]:
        """Proxy to rolling._filter_records_in_window for backward compatibility."""
        return self.rolling._filter_records_in_window(records, window_start, window_end)
