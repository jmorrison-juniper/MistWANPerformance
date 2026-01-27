"""
MistWANPerformance - Dashboard Launcher

Run this script to start the NOC dashboard web interface.

Usage:
    python run_dashboard.py
    python run_dashboard.py --port 8080
    python run_dashboard.py --debug
"""

import argparse
import logging
import sys

from src.utils.logging_config import setup_logging
from src.dashboard.app import WANPerformanceDashboard


def main():
    """Launch the WAN Performance dashboard."""
    parser = argparse.ArgumentParser(
        description="MistWANPerformance - NOC Dashboard"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host address to bind (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8050,
        help="Port number (default: 8050)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(verbose=args.debug)
    logger = logging.getLogger(__name__)
    
    logger.info("=" * 60)
    logger.info("MistWANPerformance - NOC Dashboard")
    logger.info("=" * 60)
    
    try:
        dashboard = WANPerformanceDashboard()
        dashboard.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        logger.info("[INFO] Dashboard stopped by user")
        return 0
    except Exception as error:
        logger.error(f"[ERROR] Dashboard failed: {error}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
