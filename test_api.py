"""
MistWANPerformance - API Connection Test

Quick test script to verify Mist API connectivity and credentials.
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s"
)

from src.utils.config import Config
from src.api.mist_client import MistAPIClient


def main():
    """Test Mist API connection."""
    print("=" * 60)
    print("MistWANPerformance - API Connection Test")
    print("=" * 60)
    
    try:
        # Load configuration
        config = Config()
        print("[OK] Config loaded")
        print(f"     Org ID: {config.mist.org_id}")
        print(f"     API Host: {config.mist.api_host}")
        print()
        
        # Initialize client
        client = MistAPIClient(config.mist, config.operational)
        print("[OK] API client initialized")
        print()
        
        # Test connection
        print("[...] Testing API connection...")
        if client.test_connection():
            print("[OK] API connection test passed")
            print()
            
            # Get sites
            print("[...] Retrieving sites...")
            sites = client.get_sites()
            print(f"[OK] Retrieved {len(sites)} sites")
            print()
            
            if sites:
                print("Sample sites:")
                for site in sites[:5]:
                    site_name = site.get("name", "Unknown")
                    site_id = site.get("id", "N/A")
                    print(f"  - {site_name} ({site_id})")
                if len(sites) > 5:
                    print(f"  ... and {len(sites) - 5} more")
                print()
                
                # Try to get WAN edges from first site
                first_site = sites[0]
                site_id = first_site.get("id")
                site_name = first_site.get("name", "Unknown")
                
                print(f"[...] Checking WAN edges for site: {site_name}")
                wan_edges = client.get_site_wan_edges(site_id)
                print(f"[OK] Found {len(wan_edges)} WAN edge devices")
                
                if wan_edges:
                    print()
                    print("WAN Edge devices:")
                    for device in wan_edges[:3]:
                        device_name = device.get("name", "Unknown")
                        device_model = device.get("model", "N/A")
                        print(f"  - {device_name} (Model: {device_model})")
                    if len(wan_edges) > 3:
                        print(f"  ... and {len(wan_edges) - 3} more")
            
            print()
            print("[DONE] All tests passed successfully!")
            return 0
        else:
            print("[ERROR] API connection test failed")
            return 1
            
    except ImportError as error:
        print(f"[ERROR] Missing dependency: {error}")
        print("        Run: pip install mistapi")
        return 1
    except Exception as error:
        print(f"[ERROR] {error}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
