"""
MistWANPerformance - Logging Configuration

This module provides centralized logging configuration for the application.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    log_dir: Path = Path("data/logs")
) -> logging.Logger:
    """
    Configure application-wide logging.
    
    Args:
        level: Logging level (default: INFO)
        log_file: Optional log file name (default: app.log)
        log_dir: Directory for log files
    
    Returns:
        Root logger instance
    """
    # Ensure log directory exists
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Default log file
    if log_file is None:
        log_file = "app.log"
    
    log_path = log_dir / log_file
    
    # Create root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler with simple format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_format = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_format)
    root_logger.addHandler(console_handler)
    
    # File handler with detailed format and rotation
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)  # Always capture debug to file
    file_format = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)
    root_logger.addHandler(file_handler)
    
    # Configure specific loggers
    configure_module_loggers(level)
    
    return root_logger


def configure_module_loggers(default_level: int = logging.INFO) -> None:
    """
    Configure logging levels for specific modules.
    
    Args:
        default_level: Default logging level for application modules
    """
    # Application modules
    app_modules = [
        "src.api",
        "src.collectors",
        "src.calculators",
        "src.aggregators",
        "src.loaders",
        "src.models",
        "src.utils"
    ]
    
    for module in app_modules:
        logger = logging.getLogger(module)
        logger.setLevel(default_level)
    
    # Third-party libraries - reduce noise
    noisy_libraries = [
        "urllib3",
        "requests",
        "snowflake.connector",
        "mistapi"
    ]
    
    for lib in noisy_libraries:
        logger = logging.getLogger(lib)
        logger.setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the specified name.
    
    This is a convenience function that ensures consistent logger naming.
    
    Args:
        name: Logger name (typically __name__ from calling module)
    
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


class LogContext:
    """
    Context manager for temporary logging level changes.
    
    Useful for verbose debugging of specific operations.
    """
    
    def __init__(self, logger_name: str, level: int):
        """
        Initialize log context.
        
        Args:
            logger_name: Name of logger to modify
            level: Temporary logging level
        """
        self.logger = logging.getLogger(logger_name)
        self.new_level = level
        self.original_level: int = logging.INFO  # Default fallback level
    
    def __enter__(self):
        """Enter context and set new level."""
        self.original_level = self.logger.level
        self.logger.setLevel(self.new_level)
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context and restore original level."""
        self.logger.setLevel(self.original_level)
        return False
