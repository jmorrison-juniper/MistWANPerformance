"""
Performance Timing Utilities for MistWANPerformance

Provides decorators and context managers for measuring function execution time.
Helps diagnose slow callback execution and identify bottlenecks.

Usage:
    from src.utils.performance import timed, PerformanceTimer
    
    @timed("my_function")
    def my_function():
        ...
    
    with PerformanceTimer("operation_name") as timer:
        ...
    # timer.elapsed_ms available after context exits
"""

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class PerformanceMetrics:
    """
    Collects and stores performance metrics for analysis.
    
    Singleton pattern ensures all timing data goes to one place.
    """
    
    _instance: Optional["PerformanceMetrics"] = None
    
    def __new__(cls) -> "PerformanceMetrics":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._metrics: Dict[str, List[float]] = {}
            cls._instance._enabled = True
        return cls._instance
    
    def record(self, operation: str, elapsed_ms: float) -> None:
        """Record a timing measurement."""
        if not self._enabled:
            return
        
        if operation not in self._metrics:
            self._metrics[operation] = []
        
        # Keep last 100 measurements per operation
        if len(self._metrics[operation]) >= 100:
            self._metrics[operation].pop(0)
        
        self._metrics[operation].append(elapsed_ms)
    
    def get_stats(self, operation: str) -> Dict[str, float]:
        """
        Get statistics for an operation.
        
        Returns:
            Dict with count, avg, min, max, last
        """
        measurements = self._metrics.get(operation, [])
        if not measurements:
            return {"count": 0, "avg": 0, "min": 0, "max": 0, "last": 0}
        
        return {
            "count": len(measurements),
            "avg": sum(measurements) / len(measurements),
            "min": min(measurements),
            "max": max(measurements),
            "last": measurements[-1]
        }
    
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get statistics for all recorded operations."""
        return {op: self.get_stats(op) for op in self._metrics}
    
    def clear(self) -> None:
        """Clear all metrics."""
        self._metrics.clear()
    
    def enable(self) -> None:
        """Enable metric collection."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable metric collection."""
        self._enabled = False


def get_metrics() -> PerformanceMetrics:
    """Get the global PerformanceMetrics instance."""
    return PerformanceMetrics()


class PerformanceTimer:
    """
    Context manager for timing code blocks.
    
    Usage:
        with PerformanceTimer("operation_name") as timer:
            do_work()
        print(f"Took {timer.elapsed_ms:.1f}ms")
    """
    
    def __init__(self, operation: str, log_threshold_ms: float = 100.0):
        """
        Initialize timer.
        
        Args:
            operation: Name of the operation being timed
            log_threshold_ms: Log warning if execution exceeds this (ms)
        """
        self.operation = operation
        self.log_threshold_ms = log_threshold_ms
        self.start_time: float = 0
        self.end_time: float = 0
        self.elapsed_ms: float = 0
    
    def __enter__(self) -> "PerformanceTimer":
        self.start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.end_time = time.perf_counter()
        self.elapsed_ms = (self.end_time - self.start_time) * 1000
        
        # Record to global metrics
        get_metrics().record(self.operation, self.elapsed_ms)
        
        # Log based on threshold
        if self.elapsed_ms >= self.log_threshold_ms:
            logger.warning(
                f"[PERF] {self.operation}: {self.elapsed_ms:.1f}ms (threshold: {self.log_threshold_ms}ms)"
            )
        else:
            logger.debug(f"[PERF] {self.operation}: {self.elapsed_ms:.1f}ms")


def timed(operation: str, log_threshold_ms: float = 100.0) -> Callable:
    """
    Decorator to time function execution.
    
    Args:
        operation: Name for this operation in metrics
        log_threshold_ms: Log warning if execution exceeds this (ms)
    
    Usage:
        @timed("data_provider.get_dashboard_data")
        def get_dashboard_data(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with PerformanceTimer(operation, log_threshold_ms):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def format_perf_report() -> str:
    """
    Generate a formatted performance report.
    
    Returns:
        Multi-line string with performance statistics
    """
    metrics = get_metrics()
    all_stats = metrics.get_all_stats()
    
    if not all_stats:
        return "[PERF] No performance metrics recorded"
    
    lines = ["[PERF] Performance Report:", "-" * 60]
    
    # Sort by average time descending (slowest first)
    sorted_ops = sorted(all_stats.items(), key=lambda x: x[1]["avg"], reverse=True)
    
    for operation, stats in sorted_ops:
        lines.append(
            f"  {operation}: "
            f"avg={stats['avg']:.1f}ms, "
            f"min={stats['min']:.1f}ms, "
            f"max={stats['max']:.1f}ms, "
            f"count={stats['count']}"
        )
    
    lines.append("-" * 60)
    return "\n".join(lines)
