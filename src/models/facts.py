"""
MistWANPerformance - Fact Models

Data models for fact tables in the data warehouse.
Grain: Site x Circuit x Hour
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CircuitUtilizationRecord:
    """
    Fact record for circuit utilization metrics.
    
    Primary Key: site_id + circuit_id + hour_key
    Grain: Per circuit, per hour
    """
    site_id: str
    circuit_id: str
    hour_key: str  # YYYYMMDDHH format
    utilization_pct: float
    rx_bytes: int
    tx_bytes: int
    bandwidth_mbps: int
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "circuit_id": self.circuit_id,
            "hour_key": self.hour_key,
            "utilization_pct": self.utilization_pct,
            "rx_bytes": self.rx_bytes,
            "tx_bytes": self.tx_bytes,
            "bandwidth_mbps": self.bandwidth_mbps,
            "collected_at": self.collected_at.isoformat()
        }
    
    @property
    def primary_key(self) -> str:
        """Return composite primary key."""
        return f"{self.site_id}|{self.circuit_id}|{self.hour_key}"
    
    def is_above_threshold(self, threshold_pct: float) -> bool:
        """Check if utilization exceeds threshold."""
        return self.utilization_pct >= threshold_pct


@dataclass
class CircuitStatusRecord:
    """
    Fact record for circuit status metrics.
    
    Primary Key: site_id + circuit_id + hour_key
    Grain: Per circuit, per hour
    """
    site_id: str
    circuit_id: str
    hour_key: str  # YYYYMMDDHH format
    status_code: int  # 1=up, 0=down
    up_minutes: int  # 0-60
    down_minutes: int  # 0-60
    flap_count: int
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "circuit_id": self.circuit_id,
            "hour_key": self.hour_key,
            "status_code": self.status_code,
            "up_minutes": self.up_minutes,
            "down_minutes": self.down_minutes,
            "flap_count": self.flap_count,
            "collected_at": self.collected_at.isoformat()
        }
    
    @property
    def primary_key(self) -> str:
        """Return composite primary key."""
        return f"{self.site_id}|{self.circuit_id}|{self.hour_key}"
    
    @property
    def availability_pct(self) -> float:
        """Calculate availability percentage for the hour."""
        total_minutes = self.up_minutes + self.down_minutes
        if total_minutes == 0:
            return 100.0 if self.status_code == 1 else 0.0
        return (self.up_minutes / total_minutes) * 100
    
    @property
    def status_hourly(self) -> str:
        """Return hourly status string."""
        return "Up" if self.up_minutes > 0 else "Down"


@dataclass
class CircuitQualityRecord:
    """
    Fact record for circuit quality metrics.
    
    Primary Key: site_id + circuit_id + hour_key
    Grain: Per circuit, per hour
    """
    site_id: str
    circuit_id: str
    hour_key: str  # YYYYMMDDHH format
    
    # Frame loss metrics
    frame_loss_pct: Optional[float] = None
    loss_avg: Optional[float] = None
    loss_max: Optional[float] = None
    loss_p95: Optional[float] = None
    
    # Jitter metrics (milliseconds)
    jitter_ms: Optional[float] = None
    jitter_avg: Optional[float] = None
    jitter_max: Optional[float] = None
    jitter_p95: Optional[float] = None
    
    # Latency metrics (milliseconds)
    latency_ms: Optional[float] = None
    latency_avg: Optional[float] = None
    latency_max: Optional[float] = None
    latency_p95: Optional[float] = None
    
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "circuit_id": self.circuit_id,
            "hour_key": self.hour_key,
            "frame_loss_pct": self.frame_loss_pct,
            "loss_avg": self.loss_avg,
            "loss_max": self.loss_max,
            "loss_p95": self.loss_p95,
            "jitter_ms": self.jitter_ms,
            "jitter_avg": self.jitter_avg,
            "jitter_max": self.jitter_max,
            "jitter_p95": self.jitter_p95,
            "latency_ms": self.latency_ms,
            "latency_avg": self.latency_avg,
            "latency_max": self.latency_max,
            "latency_p95": self.latency_p95,
            "collected_at": self.collected_at.isoformat()
        }
    
    @property
    def primary_key(self) -> str:
        """Return composite primary key."""
        return f"{self.site_id}|{self.circuit_id}|{self.hour_key}"
    
    def is_loss_above_threshold(self, threshold_pct: float) -> bool:
        """Check if frame loss exceeds threshold."""
        if self.frame_loss_pct is None:
            return False
        return self.frame_loss_pct >= threshold_pct
    
    def is_jitter_above_threshold(self, threshold_ms: float) -> bool:
        """Check if jitter exceeds threshold."""
        if self.jitter_ms is None:
            return False
        return self.jitter_ms >= threshold_ms
    
    def is_latency_above_threshold(self, threshold_ms: float) -> bool:
        """Check if latency exceeds threshold."""
        if self.latency_ms is None:
            return False
        return self.latency_ms >= threshold_ms


@dataclass
class FailoverEventRecord:
    """
    Fact record for circuit failover events.
    
    Tracks when traffic fails over from primary to secondary circuit.
    Primary Key: site_id + event_timestamp
    """
    site_id: str
    primary_circuit_id: str
    secondary_circuit_id: str
    event_timestamp: datetime
    event_type: str  # "failover" or "recovery"
    primary_status_before: str  # "up" or "down"
    primary_status_after: str
    secondary_status_before: str
    secondary_status_after: str
    failover_duration_seconds: Optional[int] = None  # Set on recovery
    trigger_reason: Optional[str] = None  # link_down, threshold_breach, etc.
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "primary_circuit_id": self.primary_circuit_id,
            "secondary_circuit_id": self.secondary_circuit_id,
            "event_timestamp": self.event_timestamp.isoformat(),
            "event_type": self.event_type,
            "primary_status_before": self.primary_status_before,
            "primary_status_after": self.primary_status_after,
            "secondary_status_before": self.secondary_status_before,
            "secondary_status_after": self.secondary_status_after,
            "failover_duration_seconds": self.failover_duration_seconds,
            "trigger_reason": self.trigger_reason,
            "collected_at": self.collected_at.isoformat()
        }
    
    @property
    def primary_key(self) -> str:
        """Return composite primary key."""
        return f"{self.site_id}|{self.event_timestamp.isoformat()}"


@dataclass
class RollingWindowMetrics:
    """
    Metrics for rolling time windows (3h, 12h, 24h operational windows).
    
    Different from calendar-based aggregations - these are rolling lookback windows.
    Primary Key: site_id + circuit_id + window_end + window_hours
    """
    site_id: str
    circuit_id: str
    window_end: datetime  # End of the rolling window
    window_hours: int  # 3, 12, or 24
    
    # Utilization in window
    utilization_avg: Optional[float] = None
    utilization_max: Optional[float] = None
    utilization_p95: Optional[float] = None
    
    # Time above threshold (continuous and cumulative)
    continuous_hours_above_70: float = 0.0
    continuous_hours_above_80: float = 0.0
    continuous_hours_above_90: float = 0.0
    cumulative_hours_above_70: float = 0.0
    cumulative_hours_above_80: float = 0.0
    cumulative_hours_above_90: float = 0.0
    
    # Availability in window
    availability_pct: Optional[float] = None
    flap_count: int = 0
    
    # Quality in window
    loss_avg: Optional[float] = None
    jitter_avg: Optional[float] = None
    latency_avg: Optional[float] = None
    
    calculated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "circuit_id": self.circuit_id,
            "window_end": self.window_end.isoformat(),
            "window_hours": self.window_hours,
            "utilization_avg": self.utilization_avg,
            "utilization_max": self.utilization_max,
            "utilization_p95": self.utilization_p95,
            "continuous_hours_above_70": self.continuous_hours_above_70,
            "continuous_hours_above_80": self.continuous_hours_above_80,
            "continuous_hours_above_90": self.continuous_hours_above_90,
            "cumulative_hours_above_70": self.cumulative_hours_above_70,
            "cumulative_hours_above_80": self.cumulative_hours_above_80,
            "cumulative_hours_above_90": self.cumulative_hours_above_90,
            "availability_pct": self.availability_pct,
            "flap_count": self.flap_count,
            "loss_avg": self.loss_avg,
            "jitter_avg": self.jitter_avg,
            "latency_avg": self.latency_avg,
            "calculated_at": self.calculated_at.isoformat()
        }
    
    @property
    def primary_key(self) -> str:
        """Return composite primary key."""
        return f"{self.site_id}|{self.circuit_id}|{self.window_end.isoformat()}|{self.window_hours}h"


@dataclass
class AggregatedMetrics:
    """
    Aggregated metrics for rollup tables (daily/weekly/monthly).
    
    Used for agg_circuit_* and agg_region_* tables.
    """
    site_id: str
    circuit_id: Optional[str]  # None for region-level aggregates
    period_key: str  # YYYYMMDD for daily, YYYYWW for weekly, YYYYMM for monthly
    period_type: str  # "daily", "weekly", "monthly"
    
    # Utilization aggregates
    utilization_avg: Optional[float] = None
    utilization_max: Optional[float] = None
    utilization_p95: Optional[float] = None
    hours_above_70: int = 0
    hours_above_80: int = 0
    hours_above_90: int = 0
    
    # Availability aggregates
    total_up_minutes: int = 0
    total_down_minutes: int = 0
    availability_pct: Optional[float] = None
    total_flaps: int = 0
    
    # Quality aggregates
    loss_avg: Optional[float] = None
    loss_max: Optional[float] = None
    jitter_avg: Optional[float] = None
    jitter_max: Optional[float] = None
    latency_avg: Optional[float] = None
    latency_max: Optional[float] = None
    
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for database insertion."""
        return {
            "site_id": self.site_id,
            "circuit_id": self.circuit_id,
            "period_key": self.period_key,
            "period_type": self.period_type,
            "utilization_avg": self.utilization_avg,
            "utilization_max": self.utilization_max,
            "utilization_p95": self.utilization_p95,
            "hours_above_70": self.hours_above_70,
            "hours_above_80": self.hours_above_80,
            "hours_above_90": self.hours_above_90,
            "total_up_minutes": self.total_up_minutes,
            "total_down_minutes": self.total_down_minutes,
            "availability_pct": self.availability_pct,
            "total_flaps": self.total_flaps,
            "loss_avg": self.loss_avg,
            "loss_max": self.loss_max,
            "jitter_avg": self.jitter_avg,
            "jitter_max": self.jitter_max,
            "latency_avg": self.latency_avg,
            "latency_max": self.latency_max,
            "created_at": self.created_at.isoformat()
        }
