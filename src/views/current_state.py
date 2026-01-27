"""
MistWANPerformance - Current State Views

Real-time and near-real-time views for NOC dashboards.
Shows current circuit status, congestion, and alerts.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from enum import Enum

from src.models.facts import (
    CircuitUtilizationRecord,
    CircuitStatusRecord,
    CircuitQualityRecord,
    FailoverEventRecord,
    RollingWindowMetrics
)


logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels ordered by severity."""
    INFO = 1
    WARNING = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class CircuitCurrentState:
    """
    Current state snapshot for a circuit.
    
    Used for real-time NOC dashboards.
    """
    site_id: str
    site_name: Optional[str]
    circuit_id: str
    circuit_role: str  # "primary", "secondary", "backup"
    region: Optional[str]
    
    # Status
    is_up: bool
    status_since: Optional[datetime] = None
    
    # Current utilization
    current_utilization_pct: Optional[float] = None
    utilization_trend: str = "stable"  # "rising", "falling", "stable"
    
    # Quality
    current_loss_pct: Optional[float] = None
    current_jitter_ms: Optional[float] = None
    current_latency_ms: Optional[float] = None
    
    # Alerts
    alert_severity: AlertSeverity = AlertSeverity.INFO
    alert_messages: List[str] = field(default_factory=list)
    
    # Failover status
    is_in_failover: bool = False
    failover_since: Optional[datetime] = None
    
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API/dashboard consumption."""
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "circuit_id": self.circuit_id,
            "circuit_role": self.circuit_role,
            "region": self.region,
            "is_up": self.is_up,
            "status_since": self.status_since.isoformat() if self.status_since else None,
            "current_utilization_pct": self.current_utilization_pct,
            "utilization_trend": self.utilization_trend,
            "current_loss_pct": self.current_loss_pct,
            "current_jitter_ms": self.current_jitter_ms,
            "current_latency_ms": self.current_latency_ms,
            "alert_severity": self.alert_severity.value,
            "alert_messages": self.alert_messages,
            "is_in_failover": self.is_in_failover,
            "failover_since": self.failover_since.isoformat() if self.failover_since else None,
            "last_updated": self.last_updated.isoformat()
        }


@dataclass
class SiteCongestionSummary:
    """
    Congestion summary for a site.
    
    Shows overall site health at a glance.
    """
    site_id: str
    site_name: Optional[str]
    region: Optional[str]
    
    # Circuit counts
    total_circuits: int = 0
    circuits_up: int = 0
    circuits_down: int = 0
    circuits_in_failover: int = 0
    
    # Congestion
    circuits_above_70: int = 0
    circuits_above_80: int = 0
    circuits_above_90: int = 0
    max_utilization_pct: Optional[float] = None
    
    # Overall status
    site_status: str = "healthy"  # "healthy", "degraded", "critical"
    alert_count: int = 0
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API/dashboard consumption."""
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "region": self.region,
            "total_circuits": self.total_circuits,
            "circuits_up": self.circuits_up,
            "circuits_down": self.circuits_down,
            "circuits_in_failover": self.circuits_in_failover,
            "circuits_above_70": self.circuits_above_70,
            "circuits_above_80": self.circuits_above_80,
            "circuits_above_90": self.circuits_above_90,
            "max_utilization_pct": self.max_utilization_pct,
            "site_status": self.site_status,
            "alert_count": self.alert_count
        }


class CurrentStateViews:
    """
    Generator for current state views.
    
    Provides:
    - Circuit current state (individual circuit status)
    - Site congestion summary (site-level overview)
    - Active alerts list
    - Failover status
    """
    
    # Thresholds for alerts
    UTIL_THRESHOLDS = {"warning": 70.0, "high": 80.0, "critical": 90.0}
    LOSS_THRESHOLDS = {"warning": 0.1, "high": 0.5, "critical": 1.0}
    JITTER_THRESHOLDS = {"warning": 10.0, "high": 30.0, "critical": 50.0}
    LATENCY_THRESHOLDS = {"warning": 50.0, "high": 100.0, "critical": 150.0}
    
    def __init__(
        self,
        site_lookup: Optional[Dict[str, str]] = None,
        region_lookup: Optional[Dict[str, str]] = None,
        circuit_role_lookup: Optional[Dict[str, str]] = None
    ):
        """
        Initialize current state views.
        
        Args:
            site_lookup: Mapping of site_id to site_name
            region_lookup: Mapping of site_id to region
            circuit_role_lookup: Mapping of circuit_id to role
        """
        self.site_lookup = site_lookup or {}
        self.region_lookup = region_lookup or {}
        self.circuit_role_lookup = circuit_role_lookup or {}
        logger.debug("CurrentStateViews initialized")
    
    def _determine_trend(
        self,
        recent_values: List[float],
        lookback_count: int = 3
    ) -> str:
        """
        Determine trend direction from recent values.
        
        Args:
            recent_values: List of values (newest last)
            lookback_count: Number of values to consider
        
        Returns:
            "rising", "falling", or "stable"
        """
        if len(recent_values) < 2:
            return "stable"
        
        values = recent_values[-lookback_count:]
        if len(values) < 2:
            return "stable"
        
        # Calculate average change
        changes = [values[i] - values[i-1] for i in range(1, len(values))]
        avg_change = sum(changes) / len(changes)
        
        if avg_change > 5:
            return "rising"
        elif avg_change < -5:
            return "falling"
        return "stable"
    
    def _generate_alerts(
        self,
        utilization: Optional[float],
        loss: Optional[float],
        jitter: Optional[float],
        latency: Optional[float],
        is_up: bool
    ) -> tuple:
        """
        Generate alerts based on current metrics.
        
        Returns:
            Tuple of (AlertSeverity, List[str] messages)
        """
        alerts = []
        max_severity = AlertSeverity.INFO
        
        if not is_up:
            alerts.append("Circuit is DOWN")
            max_severity = AlertSeverity.CRITICAL
        
        if utilization is not None:
            if utilization >= self.UTIL_THRESHOLDS["critical"]:
                alerts.append(f"Critical utilization: {utilization:.1f}%")
                max_severity = max(max_severity, AlertSeverity.CRITICAL, key=lambda x: x.value)
            elif utilization >= self.UTIL_THRESHOLDS["high"]:
                alerts.append(f"High utilization: {utilization:.1f}%")
                if max_severity.value < AlertSeverity.HIGH.value:
                    max_severity = AlertSeverity.HIGH
            elif utilization >= self.UTIL_THRESHOLDS["warning"]:
                alerts.append(f"Elevated utilization: {utilization:.1f}%")
                if max_severity.value < AlertSeverity.WARNING.value:
                    max_severity = AlertSeverity.WARNING
        
        if loss is not None and loss >= self.LOSS_THRESHOLDS["warning"]:
            alerts.append(f"Packet loss detected: {loss:.2f}%")
            if loss >= self.LOSS_THRESHOLDS["critical"]:
                max_severity = AlertSeverity.CRITICAL
        
        if jitter is not None and jitter >= self.JITTER_THRESHOLDS["warning"]:
            alerts.append(f"High jitter: {jitter:.1f}ms")
        
        if latency is not None and latency >= self.LATENCY_THRESHOLDS["warning"]:
            alerts.append(f"High latency: {latency:.1f}ms")
        
        return (max_severity, alerts)
    
    def get_circuit_current_state(
        self,
        site_id: str,
        circuit_id: str,
        utilization_records: List[CircuitUtilizationRecord],
        status_records: List[CircuitStatusRecord],
        quality_records: List[CircuitQualityRecord],
        failover_records: Optional[List[FailoverEventRecord]] = None
    ) -> CircuitCurrentState:
        """
        Generate current state for a single circuit.
        
        Args:
            site_id: Site UUID
            circuit_id: Circuit identifier
            utilization_records: Recent utilization records (sorted by time)
            status_records: Recent status records
            quality_records: Recent quality records
            failover_records: Recent failover events
        
        Returns:
            CircuitCurrentState object
        """
        # Get most recent records
        latest_util = utilization_records[-1] if utilization_records else None
        latest_status = status_records[-1] if status_records else None
        latest_quality = quality_records[-1] if quality_records else None
        
        # Determine current status
        is_up = latest_status.status_code == 1 if latest_status else True
        
        # Get utilization and trend
        current_util = latest_util.utilization_pct if latest_util else None
        util_values = [r.utilization_pct for r in utilization_records]
        trend = self._determine_trend(util_values)
        
        # Get quality metrics
        current_loss = latest_quality.loss_avg if latest_quality else None
        current_jitter = latest_quality.jitter_avg if latest_quality else None
        current_latency = latest_quality.latency_avg if latest_quality else None
        
        # Check failover status
        is_failover = False
        failover_since = None
        if failover_records:
            # Find most recent failover event for this circuit
            relevant = [
                f for f in failover_records
                if f.primary_circuit_id == circuit_id or f.secondary_circuit_id == circuit_id
            ]
            if relevant:
                latest_failover = max(relevant, key=lambda f: f.event_timestamp)
                if latest_failover.event_type == "failover":
                    is_failover = True
                    failover_since = latest_failover.event_timestamp
        
        # Generate alerts
        severity, alert_msgs = self._generate_alerts(
            current_util, current_loss, current_jitter, current_latency, is_up
        )
        
        return CircuitCurrentState(
            site_id=site_id,
            site_name=self.site_lookup.get(site_id),
            circuit_id=circuit_id,
            circuit_role=self.circuit_role_lookup.get(circuit_id, "unknown"),
            region=self.region_lookup.get(site_id),
            is_up=is_up,
            current_utilization_pct=round(current_util, 2) if current_util else None,
            utilization_trend=trend,
            current_loss_pct=round(current_loss, 4) if current_loss else None,
            current_jitter_ms=round(current_jitter, 2) if current_jitter else None,
            current_latency_ms=round(current_latency, 2) if current_latency else None,
            alert_severity=severity,
            alert_messages=alert_msgs,
            is_in_failover=is_failover,
            failover_since=failover_since
        )
    
    def get_site_congestion_summary(
        self,
        site_id: str,
        circuit_states: List[CircuitCurrentState]
    ) -> SiteCongestionSummary:
        """
        Generate congestion summary for a site.
        
        Args:
            site_id: Site UUID
            circuit_states: List of CircuitCurrentState for all circuits at site
        
        Returns:
            SiteCongestionSummary object
        """
        if not circuit_states:
            return SiteCongestionSummary(
                site_id=site_id,
                site_name=self.site_lookup.get(site_id),
                region=self.region_lookup.get(site_id)
            )
        
        # Count circuit states
        total = len(circuit_states)
        up_count = sum(1 for c in circuit_states if c.is_up)
        down_count = total - up_count
        failover_count = sum(1 for c in circuit_states if c.is_in_failover)
        
        # Count congestion levels
        utilizations = [c.current_utilization_pct for c in circuit_states if c.current_utilization_pct]
        above_70 = sum(1 for u in utilizations if u >= 70)
        above_80 = sum(1 for u in utilizations if u >= 80)
        above_90 = sum(1 for u in utilizations if u >= 90)
        max_util = max(utilizations) if utilizations else None
        
        # Count alerts
        alert_count = sum(len(c.alert_messages) for c in circuit_states)
        
        # Determine site status
        if down_count > 0 or above_90 > 0:
            site_status = "critical"
        elif failover_count > 0 or above_80 > 0:
            site_status = "degraded"
        else:
            site_status = "healthy"
        
        return SiteCongestionSummary(
            site_id=site_id,
            site_name=self.site_lookup.get(site_id),
            region=self.region_lookup.get(site_id),
            total_circuits=total,
            circuits_up=up_count,
            circuits_down=down_count,
            circuits_in_failover=failover_count,
            circuits_above_70=above_70,
            circuits_above_80=above_80,
            circuits_above_90=above_90,
            max_utilization_pct=round(max_util, 2) if max_util else None,
            site_status=site_status,
            alert_count=alert_count
        )
    
    def get_active_alerts(
        self,
        circuit_states: List[CircuitCurrentState],
        min_severity: AlertSeverity = AlertSeverity.WARNING
    ) -> List[Dict[str, Any]]:
        """
        Get list of active alerts across all circuits.
        
        Args:
            circuit_states: List of CircuitCurrentState objects
            min_severity: Minimum severity to include
        
        Returns:
            List of alert dictionaries
        """
        severity_order = {
            AlertSeverity.INFO: 0,
            AlertSeverity.WARNING: 1,
            AlertSeverity.HIGH: 2,
            AlertSeverity.CRITICAL: 3
        }
        min_level = severity_order[min_severity]
        
        alerts = []
        for state in circuit_states:
            if severity_order[state.alert_severity] >= min_level:
                for message in state.alert_messages:
                    alerts.append({
                        "site_id": state.site_id,
                        "site_name": state.site_name,
                        "circuit_id": state.circuit_id,
                        "region": state.region,
                        "severity": state.alert_severity.value,
                        "message": message,
                        "timestamp": state.last_updated.isoformat()
                    })
        
        # Sort by severity descending
        alerts.sort(key=lambda a: severity_order.get(AlertSeverity(a["severity"]), 0), reverse=True)
        
        logger.info(f"[OK] Found {len(alerts)} active alerts")
        return alerts
    
    def get_failover_status(
        self,
        failover_records: List[FailoverEventRecord]
    ) -> List[Dict[str, Any]]:
        """
        Get current failover status across all sites.
        
        Args:
            failover_records: Recent failover events
        
        Returns:
            List of active failover dictionaries
        """
        # Group by site and find active failovers
        site_failovers = {}
        
        for record in sorted(failover_records, key=lambda r: r.event_timestamp):
            site_id = record.site_id
            
            if record.event_type == "failover":
                site_failovers[site_id] = {
                    "site_id": site_id,
                    "site_name": self.site_lookup.get(site_id),
                    "primary_circuit_id": record.primary_circuit_id,
                    "secondary_circuit_id": record.secondary_circuit_id,
                    "failover_started": record.event_timestamp.isoformat(),
                    "trigger_reason": record.trigger_reason,
                    "status": "active"
                }
            elif record.event_type == "recovery" and site_id in site_failovers:
                # Failover has been recovered
                del site_failovers[site_id]
        
        active_failovers = list(site_failovers.values())
        logger.info(f"[OK] Found {len(active_failovers)} active failovers")
        return active_failovers    
    def get_primary_vs_secondary_comparison(
        self,
        site_id: str,
        primary_utilization: List[CircuitUtilizationRecord],
        secondary_utilization: List[CircuitUtilizationRecord],
        primary_quality: List[CircuitQualityRecord],
        secondary_quality: List[CircuitQualityRecord],
        primary_status: List[CircuitStatusRecord],
        secondary_status: List[CircuitStatusRecord],
        failover_records: Optional[List[FailoverEventRecord]] = None
    ) -> Dict[str, Any]:
        """
        Compare primary and secondary circuit metrics during failover.
        
        When primary is down/unhealthy, shows utilization on active circuit
        while preserving primary metrics for comparison.
        
        Args:
            site_id: Site UUID
            primary_utilization: Primary circuit utilization records
            secondary_utilization: Secondary circuit utilization records
            primary_quality: Primary circuit quality records
            secondary_quality: Secondary circuit quality records
            primary_status: Primary circuit status records
            secondary_status: Secondary circuit status records
            failover_records: Failover events for context
        
        Returns:
            Dictionary with comparison data for both circuits
        """
        # Get latest metrics for primary
        primary_latest_util = primary_utilization[-1] if primary_utilization else None
        primary_latest_quality = primary_quality[-1] if primary_quality else None
        primary_latest_status = primary_status[-1] if primary_status else None
        
        # Get latest metrics for secondary
        secondary_latest_util = secondary_utilization[-1] if secondary_utilization else None
        secondary_latest_quality = secondary_quality[-1] if secondary_quality else None
        secondary_latest_status = secondary_status[-1] if secondary_status else None
        
        # Determine current active circuit
        primary_is_up = primary_latest_status.status_code == 1 if primary_latest_status else True
        secondary_is_up = secondary_latest_status.status_code == 1 if secondary_latest_status else False
        
        # Check for active failover
        is_in_failover = False
        failover_since = None
        if failover_records:
            relevant = [f for f in failover_records if f.site_id == site_id]
            if relevant:
                latest = max(relevant, key=lambda f: f.event_timestamp)
                if latest.event_type == "failover":
                    is_in_failover = True
                    failover_since = latest.event_timestamp
        
        active_circuit = "primary"
        if is_in_failover or (not primary_is_up and secondary_is_up):
            active_circuit = "secondary"
        
        return {
            "site_id": site_id,
            "site_name": self.site_lookup.get(site_id),
            "is_in_failover": is_in_failover,
            "failover_since": failover_since.isoformat() if failover_since else None,
            "active_circuit": active_circuit,
            "primary": {
                "circuit_id": primary_latest_util.circuit_id if primary_latest_util else None,
                "is_up": primary_is_up,
                "is_active": active_circuit == "primary",
                "utilization_pct": round(primary_latest_util.utilization_pct, 2) if primary_latest_util else None,
                "loss_pct": round(primary_latest_quality.loss_avg, 4) if primary_latest_quality and primary_latest_quality.loss_avg else None,
                "jitter_ms": round(primary_latest_quality.jitter_avg, 2) if primary_latest_quality and primary_latest_quality.jitter_avg else None,
                "latency_ms": round(primary_latest_quality.latency_avg, 2) if primary_latest_quality and primary_latest_quality.latency_avg else None,
                "availability_pct": round(primary_latest_status.availability_pct, 2) if primary_latest_status else None,
                "flap_count": primary_latest_status.flap_count if primary_latest_status else 0
            },
            "secondary": {
                "circuit_id": secondary_latest_util.circuit_id if secondary_latest_util else None,
                "is_up": secondary_is_up,
                "is_active": active_circuit == "secondary",
                "utilization_pct": round(secondary_latest_util.utilization_pct, 2) if secondary_latest_util else None,
                "loss_pct": round(secondary_latest_quality.loss_avg, 4) if secondary_latest_quality and secondary_latest_quality.loss_avg else None,
                "jitter_ms": round(secondary_latest_quality.jitter_avg, 2) if secondary_latest_quality and secondary_latest_quality.jitter_avg else None,
                "latency_ms": round(secondary_latest_quality.latency_avg, 2) if secondary_latest_quality and secondary_latest_quality.latency_avg else None,
                "availability_pct": round(secondary_latest_status.availability_pct, 2) if secondary_latest_status else None,
                "flap_count": secondary_latest_status.flap_count if secondary_latest_status else 0
            },
            "comparison_notes": self._generate_comparison_notes(
                primary_is_up, secondary_is_up, is_in_failover,
                primary_latest_util, secondary_latest_util,
                primary_latest_quality, secondary_latest_quality
            )
        }
    
    def _generate_comparison_notes(
        self,
        primary_up: bool,
        secondary_up: bool,
        in_failover: bool,
        primary_util: Optional[CircuitUtilizationRecord],
        secondary_util: Optional[CircuitUtilizationRecord],
        primary_quality: Optional[CircuitQualityRecord],
        secondary_quality: Optional[CircuitQualityRecord]
    ) -> List[str]:
        """Generate human-readable comparison notes."""
        notes = []
        
        if in_failover:
            notes.append("Site is currently in failover state - secondary circuit is active")
        
        if not primary_up:
            notes.append("Primary circuit is DOWN")
        elif not secondary_up:
            notes.append("Secondary circuit is DOWN or unavailable")
        
        if primary_util and secondary_util:
            util_diff = primary_util.utilization_pct - secondary_util.utilization_pct
            if abs(util_diff) > 20:
                higher = "primary" if util_diff > 0 else "secondary"
                notes.append(f"Significant utilization difference: {higher} is {abs(util_diff):.1f}% higher")
        
        if primary_quality and secondary_quality:
            if primary_quality.latency_avg and secondary_quality.latency_avg:
                latency_diff = primary_quality.latency_avg - secondary_quality.latency_avg
                if abs(latency_diff) > 20:
                    higher = "primary" if latency_diff > 0 else "secondary"
                    notes.append(f"Latency difference: {higher} has {abs(latency_diff):.0f}ms higher latency")
        
        if not notes:
            notes.append("Both circuits operating normally")
        
        return notes