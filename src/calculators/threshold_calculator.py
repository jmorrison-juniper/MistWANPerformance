"""
MistWANPerformance - Threshold Calculator

Determines appropriate thresholds based on site/region configuration.
"""

import logging
from typing import Any, Dict, Optional

from src.utils.config import ThresholdConfig


logger = logging.getLogger(__name__)


class ThresholdCalculator:
    """
    Calculator for determining applicable thresholds.
    
    Supports per-region and per-store-type threshold overrides.
    """
    
    # Default quality thresholds
    DEFAULT_QUALITY_THRESHOLDS = {
        "loss": {
            "warn": 0.1,
            "high": 0.5,
            "critical": 1.0
        },
        "jitter": {
            "warn": 10.0,
            "high": 30.0,
            "critical": 50.0
        },
        "latency": {
            "warn": 50.0,
            "high": 100.0,
            "critical": 150.0
        }
    }
    
    def __init__(
        self,
        default_config: ThresholdConfig,
        region_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
        store_type_overrides: Optional[Dict[str, Dict[str, Any]]] = None
    ):
        """
        Initialize threshold calculator.
        
        Args:
            default_config: Default threshold configuration
            region_overrides: Per-region threshold overrides
            store_type_overrides: Per-store-type threshold overrides
        """
        self.default_config = default_config
        self.region_overrides = region_overrides or {}
        self.store_type_overrides = store_type_overrides or {}
        logger.debug("ThresholdCalculator initialized")
    
    def get_utilization_thresholds(
        self,
        region: Optional[str] = None,
        store_type: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Get utilization thresholds for a site.
        
        Priority: store_type > region > default
        
        Args:
            region: Site region (optional)
            store_type: Site store type (optional)
        
        Returns:
            Dictionary with warn, high, critical thresholds
        """
        thresholds = {
            "warn": self.default_config.util_warn,
            "high": self.default_config.util_high,
            "critical": self.default_config.util_critical
        }
        
        # Apply region overrides
        if region and region in self.region_overrides:
            overrides = self.region_overrides[region]
            if "util_warn" in overrides:
                thresholds["warn"] = overrides["util_warn"]
            if "util_high" in overrides:
                thresholds["high"] = overrides["util_high"]
            if "util_critical" in overrides:
                thresholds["critical"] = overrides["util_critical"]
        
        # Apply store type overrides (higher priority)
        if store_type and store_type in self.store_type_overrides:
            overrides = self.store_type_overrides[store_type]
            if "util_warn" in overrides:
                thresholds["warn"] = overrides["util_warn"]
            if "util_high" in overrides:
                thresholds["high"] = overrides["util_high"]
            if "util_critical" in overrides:
                thresholds["critical"] = overrides["util_critical"]
        
        return thresholds
    
    def get_quality_thresholds(
        self,
        metric: str,
        region: Optional[str] = None,
        store_type: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Get quality thresholds for a specific metric.
        
        Args:
            metric: Quality metric name (loss, jitter, latency)
            region: Site region (optional)
            store_type: Site store type (optional)
        
        Returns:
            Dictionary with warn, high, critical thresholds
        """
        if metric not in self.DEFAULT_QUALITY_THRESHOLDS:
            logger.warning(f"[WARN] Unknown quality metric: {metric}")
            return {"warn": 0, "high": 0, "critical": 0}
        
        # Start with defaults
        thresholds = self.DEFAULT_QUALITY_THRESHOLDS[metric].copy()
        
        # Apply region overrides
        if region and region in self.region_overrides:
            overrides = self.region_overrides[region]
            metric_key = f"{metric}_warn"
            if metric_key in overrides:
                thresholds["warn"] = overrides[metric_key]
            metric_key = f"{metric}_high"
            if metric_key in overrides:
                thresholds["high"] = overrides[metric_key]
            metric_key = f"{metric}_critical"
            if metric_key in overrides:
                thresholds["critical"] = overrides[metric_key]
        
        # Apply store type overrides
        if store_type and store_type in self.store_type_overrides:
            overrides = self.store_type_overrides[store_type]
            metric_key = f"{metric}_warn"
            if metric_key in overrides:
                thresholds["warn"] = overrides[metric_key]
            metric_key = f"{metric}_high"
            if metric_key in overrides:
                thresholds["high"] = overrides[metric_key]
            metric_key = f"{metric}_critical"
            if metric_key in overrides:
                thresholds["critical"] = overrides[metric_key]
        
        return thresholds
    
    def get_severity(
        self,
        value: float,
        thresholds: Dict[str, float]
    ) -> str:
        """
        Determine severity level based on value and thresholds.
        
        Args:
            value: Metric value
            thresholds: Dictionary with warn, high, critical thresholds
        
        Returns:
            Severity string: "normal", "warn", "high", or "critical"
        """
        if value >= thresholds["critical"]:
            return "critical"
        elif value >= thresholds["high"]:
            return "high"
        elif value >= thresholds["warn"]:
            return "warn"
        else:
            return "normal"
    
    def evaluate_circuit_health(
        self,
        utilization_pct: Optional[float] = None,
        loss_pct: Optional[float] = None,
        jitter_ms: Optional[float] = None,
        latency_ms: Optional[float] = None,
        region: Optional[str] = None,
        store_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Evaluate overall circuit health based on all metrics.
        
        Args:
            utilization_pct: Utilization percentage
            loss_pct: Packet loss percentage
            jitter_ms: Jitter in milliseconds
            latency_ms: Latency in milliseconds
            region: Site region
            store_type: Site store type
        
        Returns:
            Dictionary with individual and overall health assessment
        """
        results = {
            "utilization": {"value": utilization_pct, "severity": "unknown"},
            "loss": {"value": loss_pct, "severity": "unknown"},
            "jitter": {"value": jitter_ms, "severity": "unknown"},
            "latency": {"value": latency_ms, "severity": "unknown"},
            "overall": "unknown"
        }
        
        severities = []
        
        # Evaluate utilization
        if utilization_pct is not None:
            thresholds = self.get_utilization_thresholds(region, store_type)
            severity = self.get_severity(utilization_pct, thresholds)
            results["utilization"]["severity"] = severity
            severities.append(severity)
        
        # Evaluate loss
        if loss_pct is not None:
            thresholds = self.get_quality_thresholds("loss", region, store_type)
            severity = self.get_severity(loss_pct, thresholds)
            results["loss"]["severity"] = severity
            severities.append(severity)
        
        # Evaluate jitter
        if jitter_ms is not None:
            thresholds = self.get_quality_thresholds("jitter", region, store_type)
            severity = self.get_severity(jitter_ms, thresholds)
            results["jitter"]["severity"] = severity
            severities.append(severity)
        
        # Evaluate latency
        if latency_ms is not None:
            thresholds = self.get_quality_thresholds("latency", region, store_type)
            severity = self.get_severity(latency_ms, thresholds)
            results["latency"]["severity"] = severity
            severities.append(severity)
        
        # Determine overall health (worst case)
        if severities:
            severity_order = ["normal", "warn", "high", "critical"]
            worst = max(severities, key=lambda s: severity_order.index(s) if s in severity_order else -1)
            results["overall"] = worst
        
        return results
