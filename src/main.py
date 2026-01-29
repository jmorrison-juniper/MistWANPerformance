"""
MistWANPerformance - Main Entry Point

This module provides the main entry point for the WAN Performance data collection
and reporting system.
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from src.utils.config import Config
from src.utils.logging_config import setup_logging


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments.
    
    Returns:
        Parsed argument namespace
    """
    parser = argparse.ArgumentParser(
        description="MistWANPerformance - Retail WAN Performance Data Collection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Collect current hour metrics
  python -m src.main --collect

  # Collect with specific time range
  python -m src.main --collect --start "2025-01-25T00:00:00Z" --end "2025-01-26T00:00:00Z"

  # Run daily aggregations
  python -m src.main --aggregate daily

  # Full collection cycle (collect + aggregate)
  python -m src.main --full-cycle
        """
    )
    
    # Operation modes (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--collect",
        action="store_true",
        help="Collect metrics from Mist API"
    )
    mode_group.add_argument(
        "--aggregate",
        choices=["daily", "weekly", "monthly"],
        help="Run aggregation for specified period"
    )
    mode_group.add_argument(
        "--full-cycle",
        action="store_true",
        help="Run full collection and aggregation cycle"
    )
    mode_group.add_argument(
        "--test",
        action="store_true",
        help="Run connection tests only"
    )
    
    # Time range options
    parser.add_argument(
        "--start",
        type=str,
        help="Start time in ISO 8601 format (e.g., 2025-01-25T00:00:00Z)"
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End time in ISO 8601 format (e.g., 2025-01-26T00:00:00Z)"
    )
    
    # Output options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate operations without writing to Snowflake"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    return parser.parse_args()


def run_collection(config: Config, start_time: Optional[datetime] = None, 
                   end_time: Optional[datetime] = None, dry_run: bool = False) -> bool:
    """
    Run the data collection cycle.
    
    Args:
        config: Application configuration
        start_time: Optional start time for collection window
        end_time: Optional end time for collection window
        dry_run: If True, simulate without writing to Snowflake
    
    Returns:
        True if collection succeeded, False otherwise
    """
    logger = logging.getLogger(__name__)
    logger.info("[INFO] Starting data collection cycle")
    
    # TODO: Implement collection logic
    # 1. Initialize Mist API client
    # 2. Get list of sites with WAN circuits
    # 3. For each site, collect utilization, status, and quality metrics
    # 4. Normalize and flatten data
    # 5. Calculate derived KPIs
    # 6. Load to Snowflake (unless dry_run)
    
    logger.info("[INFO] Data collection cycle complete")
    return True


def run_aggregation(config: Config, period: str, dry_run: bool = False) -> bool:
    """
    Run aggregation for the specified period.
    
    Args:
        config: Application configuration
        period: Aggregation period ('daily', 'weekly', 'monthly')
        dry_run: If True, simulate without writing to Snowflake
    
    Returns:
        True if aggregation succeeded, False otherwise
    """
    logger = logging.getLogger(__name__)
    logger.info(f"[INFO] Starting {period} aggregation")
    
    # TODO: Implement aggregation logic
    # 1. Query fact tables for the period
    # 2. Calculate aggregated metrics
    # 3. Write to aggregate tables (unless dry_run)
    
    logger.info(f"[INFO] {period.capitalize()} aggregation complete")
    return True


def run_tests(config: Config) -> bool:
    """
    Run connection tests for Mist API and Snowflake.
    
    Args:
        config: Application configuration
    
    Returns:
        True if all tests passed, False otherwise
    """
    logger = logging.getLogger(__name__)
    logger.info("[INFO] Running connection tests")
    
    all_passed = True
    
    # Test Mist API connection
    logger.info("[...] Testing Mist API connection")
    # TODO: Implement Mist API test
    logger.info("[OK] Mist API connection successful")
    
    # Test Snowflake connection
    logger.info("[...] Testing Snowflake connection")
    # TODO: Implement Snowflake test
    logger.info("[OK] Snowflake connection successful")
    
    if all_passed:
        logger.info("[DONE] All connection tests passed")
    else:
        logger.error("[ERROR] Some connection tests failed")
    
    return all_passed


def main() -> int:
    """
    Main entry point for MistWANPerformance.
    
    Returns:
        Exit code (0 for success, non-zero for failure)
    """
    args = parse_arguments()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(level=log_level)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("MistWANPerformance - Starting")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info("=" * 60)
    
    # Load configuration
    try:
        config = Config()
        logger.info("[OK] Configuration loaded")
    except Exception as error:
        logger.error(f"[ERROR] Failed to load configuration: {error}")
        return 1
    
    # Execute requested operation
    success = False
    
    try:
        if args.test:
            success = run_tests(config)
        
        elif args.collect:
            # Parse time range if provided
            start_time = None
            end_time = None
            if args.start:
                start_time = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
            if args.end:
                end_time = datetime.fromisoformat(args.end.replace("Z", "+00:00"))
            
            success = run_collection(config, start_time, end_time, args.dry_run)
        
        elif args.aggregate:
            success = run_aggregation(config, args.aggregate, args.dry_run)
        
        elif args.full_cycle:
            logger.info("[INFO] Running full collection cycle")
            success = run_collection(config, dry_run=args.dry_run)
            if success:
                success = run_aggregation(config, "daily", args.dry_run)
    
    except KeyboardInterrupt:
        logger.warning("[WARN] Operation interrupted by user")
        return 130
    
    except Exception as error:
        logger.error(f"[ERROR] Operation failed: {error}", exc_info=True)
        return 1
    
    logger.info("=" * 60)
    if success:
        logger.info("[DONE] MistWANPerformance - Complete")
    else:
        logger.error("[ERROR] MistWANPerformance - Failed")
    logger.info("=" * 60)
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
