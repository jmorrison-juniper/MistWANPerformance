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
