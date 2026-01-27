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
├── documentation/
│   └── ...
├── agents.md
├── README.md
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## Changelog

```json
{
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
