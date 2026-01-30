# MistWANPerformance

Retail WAN Performance, Path Stability & Quality Visibility - Data Collection and Reporting Solution

## Overview

MistWANPerformance provides reliable, historical visibility into Retail WAN circuit performance and peer/path stability/quality by collecting metrics from Juniper Mist Cloud APIs and storing them in Snowflake for analysis and dashboarding.

## Target Audience

- Network Operations Center (NOC) Engineers
- Network Engineers
- Operations Leadership

## Core Questions This Solution Answers

- Which sites/circuits are congested right now and trending worse?
- Which regions/sites have chronic instability (flaps, loss, jitter, latency)?
- How often do circuits failover (primary to secondary), and what is the quality during failover?
- What is the "time above threshold" for congestion and quality issues (continuous vs cumulative)?

## Scope

| Category | Metrics |
| --- | --- |
| Utilization | WAN circuit utilization + congestion thresholding |
| Status | Circuit status (Up/Down), flaps, availability % |
| Quality | Frame loss, jitter, latency |
| Aggregations | Site/Circuit, Region, time rollups |

## Data Sources

- **Source**: Juniper Mist Cloud APIs (via mistapi SDK)
- **Warehouse**: Snowflake (SNF)

## Mist API Endpoints Reference

This section documents all Mist API endpoints used by MistWANPerformance, their purpose, and how they're utilized.

### Organization-Level Endpoints

| Endpoint | SDK Method | Purpose | Usage |
| -------- | ---------- | ------- | ----- |
| `GET /api/v1/orgs/{org_id}` | `getOrg` | Get organization details | Validate API credentials and org access |
| `GET /api/v1/orgs/{org_id}/sites` | `listOrgSites` | List all sites in org | Build site inventory and lookup table |
| `GET /api/v1/orgs/{org_id}/sitegroups` | `listOrgSiteGroups` | List site groups | Map sites to regions/groups |
| `GET /api/v1/orgs/{org_id}/inventory` | `getOrgInventory` | Get device inventory | Retrieve all gateway devices (type=gateway) |
| `GET /api/v1/orgs/{org_id}/stats/devices` | `listOrgDevicesStats` | Get device statistics | Bulk device stats including uptime, CPU, memory |
| `GET /api/v1/orgs/{org_id}/stats/ports/search` | `searchOrgSwOrGwPorts` | Search gateway port stats | WAN circuit utilization, rx/tx bytes, bandwidth |
| `GET /api/v1/orgs/{org_id}/stats/wan_clients/search` | `searchOrgWanClientStats` | Search WAN client stats | Client connection metrics |
| `GET /api/v1/orgs/{org_id}/alarms/search` | `searchOrgAlarms` | Search organization alarms | Active alerts, WAN down events |
| `GET /api/v1/orgs/{org_id}/stats/vpn_peers/search` | `searchOrgPeerPathStats` | Search VPN peer path stats | VPN tunnel quality: loss, latency, jitter, MOS |
| `GET /api/v1/orgs/{org_id}/insights/sites-sle` | `getOrgSitesSle` | Get org-wide SLE scores | Overview SLE health across all sites |
| `GET /api/v1/orgs/{org_id}/insights/sle` | `getOrgSle` | Get org SLE aggregate | Organization-level SLE summary |

### Site-Level Endpoints

| Endpoint | SDK Method | Purpose | Usage |
| -------- | ---------- | ------- | ----- |
| `GET /api/v1/sites/{site_id}/devices` | `listSiteDevices` | List devices at site | Get gateway devices for a specific site |
| `GET /api/v1/sites/{site_id}/stats/devices/{device_id}` | `getSiteDeviceStats` | Get device stats | Per-device detailed statistics |
| `GET /api/v1/sites/{site_id}/devices/events/search` | `searchSiteDeviceEvents` | Search device events | Status changes, flaps, reboots |

### Site SLE Endpoints (Deep-Dive)

| Endpoint | SDK Method | Purpose | Usage |
| -------- | ---------- | ------- | ----- |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/summary` | `getSiteSleSummary` | Get SLE summary | Current SLE score with classifier breakdown |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/summary-trend` | `getSiteSleSummaryTrend` | Get SLE trend | Historical SLE scores over time |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/histogram` | `getSiteSleHistogram` | Get SLE histogram | Score distribution for quality analysis |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/threshold` | `getSiteSleThreshold` | Get SLE threshold | Configured thresholds for SLE scoring |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/impacted-gateways` | `listSiteSleImpactedGateways` | Get impacted gateways | Gateways contributing to degradation |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/impacted-interfaces` | `listSiteSleImpactedInterfaces` | Get impacted interfaces | WAN interfaces with poor health |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/classifiers` | `listSiteSleMetricClassifiers` | Get SLE classifiers | List available classifier categories |
| `GET /api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/classifier/{classifier}/summary` | `getSiteSleClassifierDetails` | Get classifier details | Detailed breakdown for specific classifier |

**Scope Parameter** (`{scope}` and `{scope_id}`):

| Scope | scope_id | Description |
| ----- | -------- | ----------- |
| `site` | site_id | Site-wide SLE metrics |
| `gateway` | device_id | Per-gateway SLE metrics |
| `ap` | device_id | Per-AP SLE metrics |
| `switch` | device_id | Per-switch SLE metrics |
| `client` | mac | Per-client SLE metrics |

**SLE Metrics** (`{metric}` parameter):

| Metric | Scope | Description |
| ------ | ----- | ----------- |
| `gateway-health` | site, gateway | Overall gateway health score |
| `wan-link-health` | site, gateway | WAN circuit health (loss, jitter, latency) |
| `application_health` | site, gateway | Application performance health |
| `switch_health` | site, switch | Switch health metrics |
| `switch_throughput` | site, switch | Switch throughput metrics |
| `coverage` | site, ap | Wireless coverage metrics |
| `capacity` | site, ap | Wireless capacity metrics |
| `throughput` | site, ap | Wireless throughput metrics |
| `time-to-connect` | site, ap | Wireless connection time |
| `roaming` | site, ap | Wireless roaming metrics |

**Classifiers** (`{classifier}` parameter - returned by `listSiteSleMetricClassifiers`):

For `wan-link-health`:

| Classifier | Description |
| ---------- | ----------- |
| `network-loss` | Packet loss percentage |
| `network-jitter` | Network jitter in milliseconds |
| `network-latency` | Round-trip latency in milliseconds |
| `interface-congestion` | Interface congestion events |
| `interface-port-down` | Port down events |
| `isp-reachability-dhcp` | DHCP reachability issues |
| `isp-reachability-arp` | ARP reachability issues |

For `gateway-health`:

| Classifier | Description |
| ---------- | ----------- |
| `cpu-usage` | Gateway CPU utilization |
| `memory-usage` | Gateway memory utilization |
| `disk-usage` | Gateway disk utilization |

### API Usage Patterns

**Pagination**: All list/search endpoints support pagination:

- `limit`: Max items per page (default 1000)
- `page`: Page number for page-based pagination
- `search_after`: Cursor for cursor-based pagination (search endpoints)

**Rate Limiting**: Mist API enforces rate limits:

- 5000 calls per hour per org
- 429 responses trigger automatic backoff
- Rate limit state tracked and displayed in dashboard status bar

#### Example: Get All VPN Peer Paths with Pagination

```python
from src.api.mist_client import MistAPIClient

client = MistAPIClient()
result = client.get_org_vpn_peer_stats()  # Handles pagination automatically

if result["success"]:
    print(f"Total peers: {result['total_peers']}")
    for port_id, peers in result["peers_by_port"].items():
        for peer in peers:
            print(f"  {peer['vpn_name']}: latency={peer['latency']}ms, loss={peer['loss']}%")
```

#### Example: Get Site SLE Details

```python
from src.api.mist_client import MistAPIClient

client = MistAPIClient()
site_id = "your-site-uuid"

# Get SLE summary
summary = client.get_site_sle_summary(site_id, metric="wan-link-health", duration="1w")

# Get impacted gateways
gateways = client.get_site_sle_impacted_gateways(site_id, metric="wan-link-health", duration="1w")

# Get classifier breakdown (loss, jitter, latency)
classifiers = client.get_site_sle_classifiers(site_id, metric="wan-link-health", duration="1w")
```

## KPI Definitions

### 1. Utilization (Site/Circuit Level)

- **Time Grain**: Hourly (required)
- **Thresholds**: 70%, 80%, 90% (configurable, with optional overrides by region/store type)
- **Formula**: `utilization_pct = max(rx_bytes, tx_bytes) / bandwidth_bytes * 100`

### 2. Time Above Threshold

Two modes (both required):

| Mode | Definition |
| --- | --- |
| Continuous | Longest consecutive run above threshold within a period |
| Cumulative | Total hours above threshold within a period |

**Periods**: 3h, 12h, 24h operational windows; daily/weekly/monthly calendar

### 3. Circuit Status & Flaps

- **Status Snapshot (hourly)**:
  - `up_minutes`: Minutes circuit was up within the hour (0-60)
  - `down_minutes`: 60 - up_minutes
  - `status_hourly`: "Up" if up_minutes > 0
- **Flap Count**: Count of Up->Down or Down->Up transitions per hour/day/week

### 4. Availability Percentage

- **Formula**: `availability_pct = up_minutes / total_minutes * 100`
- **Periods**: Daily, weekly, monthly, 13-month rolling

### 5. Quality Metrics (Site/Circuit Level)

| Metric | Statistics | Thresholds (configurable) |
| --- | --- | --- |
| Frame Loss | avg, max, p95 | 0.1%, 0.5%, 1.0% |
| Jitter | avg, max, p95 | 10ms, 30ms, 50ms |
| Latency | avg, max, p95 | 50ms, 100ms, 150ms |

## Dimensions

| Dimension | Attributes |
| --- | --- |
| Site | site_id, site_name, region |
| Circuit | bandwidth_mbps, role (primary/secondary), active_state |
| Time | hourly grain canonical; day/week/month rollups |

**Grain**: Site x Circuit x Hour

## Aggregations

### By Geography

- Region (required)

### By Time

| Type | Periods |
| --- | --- |
| Operational Windows | 3h, 12h, 24h |
| Calendar | Daily, weekly, monthly |
| Historic | 13 months |

## Outputs

### Dashboards / Views

- **Executive Overview**: Trends, top offenders
- **Engineering View**: Live congestion + quality, drill to site/circuit, availability + flaps + chronic offenders

### Drilldowns

- Region -> Site List -> Site Detail -> Circuit Detail -> Time Series
- Exportable "Top Offenders" tables

## Installation

### Prerequisites

- Python 3.10+
- Snowflake account with appropriate permissions
- Mist API token with org-level read access

### Setup

```bash
# Clone the repository
git clone <repository-url>
cd MistWANPerformance

# Create virtual environment (Windows)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies (UV preferred, pip fallback)
uv pip install -r requirements.txt
# OR
pip install -r requirements.txt

# Copy environment template and configure
copy .env.example .env
# Edit .env with your credentials
```

### Configuration

Edit `.env` with your credentials:

```bash
# Mist API Configuration
MIST_API_TOKEN=your_api_token
MIST_ORG_ID=your_org_id

# Snowflake Configuration
SNF_ACCOUNT=your_account
SNF_USER=your_user
SNF_PASSWORD=your_password
SNF_DATABASE=WAN_PERFORMANCE
SNF_SCHEMA=RETAIL_WAN
SNF_WAREHOUSE=COMPUTE_WH
```

## Container Deployment (Recommended)

Run the entire stack in containers using Podman or Docker:

### Quick Start

```bash
# Configure credentials
copy .env.example .env
# Edit .env with your Mist API credentials

# Build and start all services
podman-compose up -d

# View dashboard at http://localhost:8050
```

### Container Commands

```bash
# Start services (builds if needed)
podman-compose up -d

# Rebuild after code changes
podman-compose build
podman-compose up -d

# View logs
podman-compose logs -f dashboard    # Dashboard logs
podman-compose logs -f redis        # Redis logs

# Stop services (data persists)
podman-compose down

# Stop and remove all data
podman-compose down -v
```

### Container Architecture

The stack includes two services:

| Service   | Port | Description                        |
|-----------|------|------------------------------------|
| dashboard | 8050 | Dash web application               |
| redis     | 6379 | Data cache with 31-day persistence |

Data is stored in persistent Docker volumes:

- `mistwan-app-data`: Application logs and exports
- `mistwan-redis-data`: Redis cache (31-day retention)

### Docker Users

Replace `podman-compose` with `docker-compose`:

```bash
docker-compose up -d
docker-compose down
```

## Usage

### Run Data Collection

```bash
# Collect current hour metrics
python -m src.main --collect

# Collect with specific time range
python -m src.main --collect --start "2025-01-25T00:00:00Z" --end "2025-01-26T00:00:00Z"

# Run daily aggregations
python -m src.main --aggregate daily

# Full collection cycle (collect + aggregate)
python -m src.main --full-cycle
```

### Run Dashboard

```bash
# Start the NOC dashboard (default: http://127.0.0.1:8050)
python run_dashboard.py

# Use a different port
python run_dashboard.py --port 8080

# Allow external connections
python run_dashboard.py --host 0.0.0.0

# Enable debug mode
python run_dashboard.py --debug
```

## Project Structure

```text
MistWANPerformance/
├── .github/
│   └── copilot-instructions.md
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── mist_client.py
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── utilization_collector.py
│   │   ├── status_collector.py
│   │   └── quality_collector.py
│   ├── calculators/
│   │   ├── __init__.py
│   │   ├── kpi_calculator.py
│   │   └── threshold_calculator.py
│   ├── aggregators/
│   │   ├── __init__.py
│   │   └── time_aggregator.py
│   ├── loaders/
│   │   ├── __init__.py
│   │   └── snowflake_loader.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── dimensions.py
│   │   └── facts.py
│   ├── views/
│   │   ├── __init__.py
│   │   ├── current_state.py
│   │   └── rankings.py
│   ├── dashboard/
│   │   ├── __init__.py
│   │   ├── app.py
│   │   └── data_provider.py
│   └── utils/
│       ├── __init__.py
│       ├── config.py
│       └── logging_config.py
├── tests/
│   └── ...
├── data/
│   ├── logs/
│   ├── exports/
│   └── cache/
├── agents.md
├── README.md
├── requirements.txt
├── pyproject.toml
├── run_dashboard.py
└── .env.example
```

## Changelog

```json
{
  "26.02.02.10.30": {
    "performance": [
      "Async precomputers using asyncio.TaskGroup for I/O parallelism (50 sites concurrent)",
      "ProcessPoolExecutor for CPU-bound computations (site status, utilization distribution, region summary)",
      "Dedicated asyncio event loop running in background thread for precomputation",
      "asyncio.gather() for parallel executor operations",
      "asyncio.to_thread() for blocking Redis operations"
    ],
    "feature-additions": [
      "AsyncDashboardPrecomputer: Parallelized dashboard data computation",
      "AsyncSiteSlePrecomputer: Parallel per-site SLE precomputation (50 concurrent)",
      "AsyncSiteVpnPrecomputer: Parallel per-site VPN precomputation (50 concurrent)",
      "start_async_precomputers() and stop_async_precomputers() management functions"
    ],
    "api-changes": [
      "New module: src/cache/async_precompute.py with async precomputers",
      "CPU-bound functions: compute_site_statuses_cpu(), compute_utilization_distribution_cpu()",
      "CPU-bound functions: compute_region_summary_cpu(), compute_top_congested_cpu()",
      "Shared process pool via get_process_pool() / shutdown_process_pool()"
    ],
    "refactoring": [
      "Replaced threading-based precomputers with asyncio-based implementations",
      "Centralized graceful shutdown via stop_async_precomputers()"
    ]
  },
  "26.02.01.09.00": {
    "documentation": [
      "Comprehensive Mist API Endpoints Reference section added to README",
      "All 20+ endpoints documented with SDK method, purpose, and usage",
      "Code examples for pagination and SLE deep-dive queries"
    ],
    "feature-additions": [
      "Dashboard status bar shows SLE cache status: fresh/stale/missing counts",
      "SLE refresh activity shows collection cycles and degraded sites progress"
    ],
    "bug-fixes": [
      "Missing sites now prioritized over stale sites in SLE refresh queue",
      "get_sites_needing_sle_refresh() returns missing sites first, then stale"
    ],
    "api-changes": [
      "RedisCache: get_site_sle_cache_status() for fresh/stale/missing counts",
      "WANPerformanceDashboard: _get_sle_cache_status() helper method"
    ],
    "performance": [
      "SLE background worker logs detailed coverage status per cycle"
    ]
  },
  "26.01.31.16.30": {
    "feature-additions": [
      "VPN peer path metrics collection from Mist API",
      "VPN peer path bricks on main dashboard (Total Peers, Paths Up, Paths Down, VPN Health %)",
      "VPN peer path table in site SLE detail view with loss, latency, jitter, MOS",
      "VPNPeerBackgroundWorker for continuous peer path collection (5-minute intervals)"
    ],
    "api-changes": [
      "MistAPIClient: get_vpn_peer_stats() using searchOrgPeerPathStats endpoint",
      "MistAPIClient: get_org_vpn_peer_stats(), get_site_vpn_peer_stats() convenience methods",
      "DashboardDataProvider: get_vpn_peer_summary(), get_site_vpn_peers(), get_vpn_peer_table_data()"
    ],
    "data-model-changes": [
      "Redis key pattern: mistwan:vpn_peers:{site_id}:{mac} for per-gateway storage",
      "VPN peer data includes: vpn_name, peer_router_name, port_id, up, latency, loss, jitter, mos",
      "6 new cache methods for VPN peer storage and retrieval"
    ],
    "dashboard": [
      "New VPN Peer Path row with 4 status bricks on main overview",
      "_build_vpn_peer_table() for site-level peer path display",
      "_build_vpn_peer_section() for VPN section with count badge",
      "Conditional styling: Up=green, Down=red, high loss=orange, low MOS=yellow"
    ],
    "performance": [
      "5-minute refresh interval for VPN peer collection",
      "Rate-limited collection: 5 seconds between API calls",
      "31-day TTL for historical data persistence"
    ]
  },
  "26.01.31.09.30": {
    "feature-additions": [
      "Site SLE detail drill-down view when clicking degraded site row",
      "SLE summary time-series chart showing total vs degraded over time",
      "SLE histogram bar chart showing score distribution",
      "Impacted gateways table with degraded percentage",
      "Impacted interfaces table with degraded percentage",
      "Classifier breakdown display (network-loss, jitter, latency)"
    ],
    "api-changes": [
      "_build_site_sle_detail() method for full detail view rendering",
      "_build_sle_summary_chart() for time-series visualization",
      "_build_sle_histogram_chart() for score distribution",
      "_build_impacted_gateways_table() and _build_impacted_interfaces_table()"
    ],
    "dashboard": [
      "SLE Degraded Sites table now has row_selectable=single",
      "New callback: handle_sle_table_click() for drill-down navigation",
      "New callback: handle_sle_back_click() to return to main view",
      "Cache status badge (Fresh/Stale) in detail view header"
    ],
    "documentation": [
      "Task F4: Dashboard Integration marked complete",
      "Full Site-Level SLE Deep-Dive feature marked complete"
    ]
  },
  "26.01.30.23.45": {
    "feature-additions": [
      "Site-level SLE collector for degraded site deep-dives",
      "SLECollector class with collect_for_site(), collect_for_degraded_sites(), collect_for_all_sites()",
      "SLEBackgroundWorker for continuous background SLE data collection",
      "Prioritizes degraded sites first, then collects all sites incrementally"
    ],
    "api-changes": [
      "MistAPIClient: get_site_sle_summary(), get_site_sle_histogram(), get_site_sle_threshold()",
      "MistAPIClient: get_site_sle_impacted_gateways(), get_site_sle_impacted_interfaces()",
      "MistAPIClient: get_site_sle_classifiers()",
      "DashboardDataProvider: get_site_sle_details() for cached SLE data retrieval"
    ],
    "data-model-changes": [
      "Redis key pattern: mistwan:site_sle:{site_id}:{data_type}:{metric}",
      "Redis key: mistwan:site_sle:last_fetch:{site_id} for incremental fetching",
      "12 new cache methods for site-level SLE storage and retrieval"
    ],
    "performance": [
      "Rate-limited collection: 2 seconds between site API calls",
      "Cache freshness check to skip recently updated sites",
      "Incremental fetching using last timestamp"
    ],
    "documentation": [
      "Updated TODO.md Tasks F1-F3 as complete"
    ]
  },
  "26.01.29.16.45": {
    "feature-additions": [
      "Redis caching for SLE data, worst sites, and alarms"
    ],
    "performance": [
      "SLE snapshot persisted to Redis with 7-day TTL",
      "Worst sites persisted to Redis with 1-hour TTL",
      "Alarms persisted to Redis with 7-day TTL"
    ],
    "api-changes": [
      "save_sle_snapshot() now called after SLE API fetch",
      "save_worst_sites_sle() now called after worst sites fetch",
      "save_alarms() now called after alarms fetch"
    ]
  },
  "26.01.30.22.10": {
    "feature-additions": [
      "AsyncMistAPIClient for true async HTTP API calls using aiohttp",
      "AsyncMistConnection with aiohttp.ClientSession management",
      "AsyncMistStatsOperations with async port stats fetching",
      "Updated AsyncBackgroundRefreshWorker to support use_async_api parameter"
    ],
    "performance": [
      "True async HTTP using aiohttp instead of sync requests in executor",
      "Async rate limiting using asyncio.sleep() instead of blocking sleep",
      "Async retry logic with exponential backoff"
    ],
    "api-changes": [
      "AsyncMistAPIClient - full async facade for Mist API operations",
      "AsyncMistConnection - async session management with aiohttp",
      "AsyncMistStatsOperations - async get_org_gateway_port_stats_async()",
      "AsyncBackgroundRefreshWorker.use_async_api - enables true async API mode",
      "429 rate limit handling shared with sync client via RateLimitState singleton"
    ],
    "testing": [
      "Added 13 pytest-asyncio tests for async API client",
      "All tests pass"
    ],
    "documentation": [
      "Updated TODO.md Task 5 (Mist API Client Async) as complete",
      "Added aiohttp>=3.9.0 to requirements.txt"
    ]
  },
  "26.01.29.20.55": {
    "feature-additions": [
      "Added get_site_sle_trend() to MistInsightsOperations for site-specific SLE deep-dives"
    ],
    "api-changes": [
      "MistInsightsOperations.get_site_sle_trend() - retrieves SLE time-series for individual sites",
      "MistAPIClient.get_site_sle_trend() - facade delegation for site SLE trend",
      "Supports gateway-health, wan-link-health, application-health metrics"
    ],
    "documentation": [
      "Updated TODO.md Task C (Site-Level SLE) as complete"
    ]
  },
  "26.01.30.21.40": {
    "feature-additions": [
      "AsyncBackgroundRefreshWorker class for asyncio-based cache refresh",
      "refresh_stale_sites_parallel() function using asyncio.TaskGroup for structured concurrency",
      "Parallel site refresh with configurable concurrency limit (default: 5)"
    ],
    "performance": [
      "Async refresh loop using asyncio.sleep() instead of blocking sleep",
      "Blocking API calls run in executor to avoid blocking event loop",
      "Semaphore-based concurrency limiting for parallel site refresh"
    ],
    "api-changes": [
      "AsyncBackgroundRefreshWorker - async equivalent of BackgroundRefreshWorker",
      "refresh_stale_sites_parallel() - TaskGroup-based parallel refresh",
      "Updated cache/__init__.py to export new async classes"
    ],
    "testing": [
      "Added 12 unit tests for background refresh (async and legacy)",
      "Added pytest-asyncio dependency for async test support",
      "All 69 tests pass"
    ],
    "documentation": [
      "Updated TODO.md Task 4 as complete"
    ]
  },
  "26.01.30.21.00": {
    "feature-additions": [
      "ProcessPoolExecutor for time aggregation (aggregate_daily_to_weekly_parallel, aggregate_daily_to_monthly_parallel, aggregate_to_region_parallel)"
    ],
    "performance": [
      "Parallel daily-to-weekly rollup using CPU_COUNT workers",
      "Parallel daily-to-monthly rollup using CPU_COUNT workers",
      "Parallel region aggregation using CPU_COUNT workers"
    ],
    "api-changes": [
      "_merge_aggregates_worker() - serializable worker function for parallel aggregation",
      "Original class methods preserved for backward compatibility"
    ],
    "testing": [
      "Added 4 unit tests for parallel aggregation validation",
      "Tests verify parallel results match sequential results"
    ],
    "documentation": [
      "Updated TODO.md Task 3 as complete"
    ]
  },
  "26.01.30.20.25": {
    "feature-additions": [
      "Dashboard SLE cards: SLE Gateway, SLE WAN Link, SLE App, SLE Degraded Sites",
      "Dashboard Alarms cards: Total Alarms, Critical Alarms (24h)",
      "SLE data loading at dashboard startup (3208 sites, gateway-health scores)",
      "Worst sites retrieval for gateway-health and wan-link-health metrics",
      "Alarms search with pagination (10,393 alarms in 24h)"
    ],
    "api-changes": [
      "DashboardDataProvider.update_sle_data() - stores SLE snapshot",
      "DashboardDataProvider.update_worst_sites() - stores worst performing sites",
      "DashboardDataProvider.update_alarms() - stores alarms with severity/type breakdown",
      "DashboardDataProvider.get_sle_summary() - computes SLE metrics for display",
      "DashboardDataProvider.get_alarms_summary() - computes alarm counts for display"
    ],
    "documentation": [
      "Updated TODO.md Task E as complete with implementation details"
    ]
  },
  "26.01.29.20.45": {
    "feature-additions": [
      "Redis caching for SLE data: save_sle_snapshot(), get_sle_snapshot(), save_worst_sites_sle()",
      "Redis caching for Alarms: save_alarms(), get_alarms(), get_alarm_by_id()",
      "Incremental fetch support: get_last_sle_timestamp(), get_last_alarms_timestamp()",
      "Alarm filter methods: get_alarms_by_type(), get_alarms_by_site()"
    ],
    "data-model-changes": [
      "Added PREFIX_SLE and PREFIX_ALARMS to RedisCache",
      "SLE cached with 7-day TTL, worst sites with 1-hour TTL",
      "Individual alarms stored by ID for deduplication"
    ]
  },
  "26.01.29.20.15": {
    "feature-additions": [
      "Added MistInsightsOperations class for SLE and Alarms API operations",
      "Added get_org_sites_sle() - retrieves SLE scores for all 3208 sites",
      "Added get_org_worst_sites_by_sle() - retrieves worst performing sites by metric",
      "Added search_org_alarms() - searches org alarms with type filtering and pagination"
    ],
    "api-changes": [
      "Integrated MistInsightsOperations into MistAPIClient facade",
      "Added new insights_ops property to MistAPIClient"
    ],
    "documentation": [
      "Updated TODO.md with SLE/Alarms API testing results and response structures"
    ]
  },
  "25.01.30.14.30": {
    "feature-additions": [
      "ProcessPoolExecutor support for bulk KPI calculations (calculate_availability_bulk, create_daily_aggregates_parallel)",
      "Port filtering now excludes disabled and down WAN ports from utilization data"
    ],
    "performance": [
      "Parallel availability calculation for multiple circuits using CPU_COUNT workers",
      "Parallel daily aggregate creation with serializable dict inputs/outputs"
    ],
    "api-changes": [
      "KPICalculator.calculate_availability_bulk() - parallel availability for circuit batches",
      "KPICalculator.create_daily_aggregates_parallel() - parallel daily aggregates",
      "Worker functions use serializable dicts to avoid pickling issues"
    ],
    "bug-fixes": [
      "Disabled WAN ports (disabled=true) now excluded from port stats processing",
      "Down WAN ports (up=false) now excluded from port stats processing",
      "Added wan_down_count and wan_disabled_count tracking in port batch processing"
    ]
  },
  "25.01.28.18.15": {
    "feature-additions": [
      "Full containerized deployment with Dockerfile and updated docker-compose.yml",
      "Multi-stage Docker build for smaller production images",
      "Container-friendly Redis connection using REDIS_HOST/REDIS_PORT env vars"
    ],
    "documentation": [
      "Container deployment section added to README",
      "Podman-compose and docker-compose usage instructions"
    ],
    "compatibility": [
      "RedisCache supports REDIS_URL, REDIS_HOST/PORT, or localhost fallback",
      ".dockerignore for clean container builds"
    ]
  },
  "25.01.28.16.30": {
    "feature-additions": [
      "Incremental cache saves during API fetch - data saved as each batch arrives",
      "Fetch session tracking with resume capability on restart",
      "on_batch callback parameter for MistAPIClient.get_org_gateway_port_stats()"
    ],
    "api-changes": [
      "MistStatsOperations.get_org_gateway_port_stats() accepts on_batch callback",
      "MistAPIClient facade passes through on_batch parameter"
    ],
    "data-model-changes": [
      "RedisCache.start_fetch_session() - tracks fetch progress",
      "RedisCache.save_batch_incrementally() - saves batches as they arrive",
      "RedisCache.get_incomplete_fetch_session() - checks for resumable sessions",
      "RedisCache._append_site_port_stats() - merges data across batches"
    ],
    "performance": [
      "Interrupted fetches preserve all completed batches",
      "Restart recovers data from partial fetch sessions"
    ]
  },
  "25.01.28.15.00": {
    "feature-additions": [
      "Redis 31-day historical data retention with HISTORY_TTL constant",
      "Historical time-series methods: append_historical_record(), get_historical_records(), prune_old_history(), get_history_stats()",
      "Redis persistence configuration methods: get_persistence_config(), force_save()",
      "Startup persistence check with warnings if AOF/RDB not configured",
      "Background refresh worker triggers force_save after each refresh cycle"
    ],
    "data-model-changes": [
      "Added PREFIX_HISTORY for time-series data using Redis Sorted Sets",
      "Historical records stored with timestamp score for efficient range queries"
    ],
    "documentation": [
      "docker-compose.yml for Redis with persistence volume",
      "redis.conf with AOF (appendfsync everysec) and RDB persistence",
      "Updated .env.example with REDIS_HISTORY_TTL documentation",
      "Updated ProjectGoals.md with Mist API WAN SLE and health endpoints"
    ],
    "performance": [
      "Data persists across Redis restarts using AOF + RDB backup",
      "31-day retention window for historical analysis"
    ]
  },
  "25.01.28.12.15": {
    "feature-additions": [
      "Redis caching layer for Mist API data (src/cache/redis_cache.py)",
      "Cache freshness checking with configurable stale threshold",
      "Automatic cache-first loading in dashboard startup"
    ],
    "performance": [
      "Dashboard startup uses cached data when fresh, reducing API load",
      "Removed API batch limits (max_batches=100) for complete data retrieval"
    ],
    "documentation": [
      "Added Redis configuration options to .env.example",
      "Added redis>=5.0.0 to requirements.txt"
    ]
  },
  "26.01.27.17.00": {
    "feature-additions": [
      "Added run_dashboard.py launcher script for NOC dashboard"
    ],
    "documentation": [
      "Updated README with dashboard launch instructions",
      "Updated project structure to include views/ and dashboard/ folders"
    ],
    "bug-fixes": [
      "Fixed Pylance type errors in dashboard app.py",
      "Fixed markdown table alignment in ProjectGoals.md"
    ]
  },
  "26.01.27.16.30": {
    "feature-additions": [
      "Added active_state field to DimCircuit for tracking which circuit is carrying traffic",
      "Added Primary vs Secondary comparison view in CurrentStateViews.get_primary_vs_secondary_comparison()",
      "Added drilldown navigation to dashboard: Region -> Site -> Circuit -> Time Series",
      "Added CSV export functionality for Top Offenders and Active Alerts tables",
      "Added breadcrumb navigation for drilldown state tracking",
      "Added DashboardDataProvider.get_region_sites() for region drilldown",
      "Added DashboardDataProvider.get_site_circuits() for site drilldown",
      "Added DashboardDataProvider.get_circuit_timeseries() for circuit time series view",
      "Added DashboardDataProvider.get_primary_secondary_comparison() for failover comparison"
    ],
    "data-model-changes": [
      "DimCircuit now includes active_state boolean field",
      "DimCircuit.from_mist_device_port() now determines active_state from port data"
    ],
    "documentation": [
      "Reformatted ProjectGoals.md with proper markdown structure and tables"
    ],
    "testing": [
      "All 53 tests passing"
    ]
  },
  "26.01.26.14.30": {
    "feature-additions": [
      "Added FailoverEventRecord model for tracking circuit failovers",
      "Added RollingWindowMetrics model for 3h/12h/24h operational windows",
      "Implemented rolling window aggregations in TimeAggregator",
      "Created src/views/ module with RankingViews and CurrentStateViews",
      "Added top-N rankings for utilization, availability, flaps",
      "Added chronic offender detection for repeated threshold breaches",
      "Created Dash/Plotly NOC dashboard with real-time monitoring",
      "Added DashboardDataProvider for connecting data to dashboard"
    ],
    "data-model-changes": [
      "Extended facts.py with FailoverEventRecord and RollingWindowMetrics",
      "Added continuous and cumulative hours_above_threshold to rolling windows"
    ],
    "kpi-changes": [
      "Implemented 3h/12h/24h rolling window calculations",
      "Added calculate_rolling_windows_for_circuit method"
    ],
    "testing": [
      "Added test_views.py for RankingViews and CurrentStateViews",
      "Added test_time_aggregator.py for rolling window tests"
    ],
    "documentation": [
      "Added dash, plotly, dash-bootstrap-components to requirements.txt"
    ]
  },
  "25.01.27.14.30": {
    "refactoring": [
      "SnowflakeLoader split into SnowflakeConnection, SnowflakeSchemaManager, SnowflakeFactLoader + facade",
      "TimeAggregator split into AggregateCalculator, CalendarAggregator, RollingWindowAggregator, RegionAggregator + facade",
      "MistAPIClient split into MistConnection, MistSiteOperations, MistStatsOperations + facade",
      "StatusCollector refactored to use StatusRecordInput and TimeWindow dataclasses",
      "KPICalculator refactored to use DailyAggregateInput dataclass"
    ],
    "bug-fixes": [
      "Fixed AlertSeverity enum using string values causing incorrect severity comparisons",
      "Fixed type annotations in time_aggregator.py for Dict return types"
    ],
    "testing": [
      "All 53 tests passing after refactoring"
    ]
  },
  "26.01.26.11.15": {
    "documentation": [
      "Added autonomous agent workflow with 7-step process to agents.md and copilot-instructions.md",
      "Added Python 5-item rule for project hierarchy and function limits",
      "Added comprehensive safe_input pattern with EOF handling",
      "Added Dash 3.x API changes warning",
      "Added project-specific naming conventions and AI marker avoidance",
      "Enhanced Windows path compatibility notes"
    ]
  },
  "26.01.26.10.30": {
    "bug-fixes": [
      "Fixed Pylance type checking errors in mist_client.py",
      "Proper type annotations for conditional imports (mistapi)",
      "Fixed kwargs naming conflicts and Union type hints"
    ],
    "documentation": [
      "Added development environment section to agents.md",
      "Added agent workflow requirements to agents.md",
      "Added Mist API device type filtering note to agents.md",
      "Enhanced coding style conventions with security and naming rules"
    ]
  },
  "26.01.26.00.00": {
    "feature-additions": [
      "Initial project structure created",
      "Copilot instructions and agents.md configured",
      "Data models defined for dimensions and facts",
      "KPI calculation framework established"
    ],
    "documentation": [
      "README with full project documentation",
      "Requirements specification implemented"
    ]
  }
}
```

## License

Internal use only - Hewlett Packard Enterprise

## References

- Mist API Documentation: <https://api.mist.com/api/v1/docs>
- Thomas Munzer's mistapi: <https://github.com/tmunzer/mistapi_python>
- Snowflake Python Connector: <https://docs.snowflake.com/en/developer-guide/python-connector>
