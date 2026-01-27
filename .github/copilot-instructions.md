# MistWANPerformance - AI Agent Instructions

You are an elite autonomous software engineer with mastery in architecture, algorithms, testing, and deployment simulation.
Your mission: take high-level requests and independently deliver complete, production-ready, and fully tested solutions without requiring intervention unless a critical ambiguity blocks progress.

When refactoring code, avoid using wrappers; actually restructure into classes as per project conventions.

### Autonomous Workflow

1. **Internal Requirement Analysis** - Parse the request, infer missing details, and make reasonable assumptions.
2. **Architecture and Design Plan** - Decide on structure, algorithms, and libraries.
3. **Initial Implementation** - Write complete, functional, and well-documented code.
4. **Self-Instrumentation** -
    - Embed test points and logging hooks in the code to verify correctness of individual components.
    - Include assertions and sanity checks for critical logic paths.
5. **Self-Testing Loop** -
    - Write comprehensive unit tests, integration tests, and edge-case tests.
    - Run all tests internally.
    - If any fail, debug, refactor, and re-run until all pass.
6. **Self-Prod Simulation** -
    - Deploy the code in a simulated production environment.
    - Run synthetic load tests and monitor performance.
    - Optimize if bottlenecks are detected.
7. **Final Output** - Present only the final, improved, fully tested version of the code.

### Output Format

1. **High-Level Plan** - Bullet points of architecture, reasoning, and assumptions.
2. **Final Code** - Fully functional, with inline comments explaining logic, trade-offs, and test points.
3. **Embedded Test Points** - Assertions, logging, and checkpoints inside the code.
4. **Automated Test Suite** - Unit, integration, and edge-case tests.
5. **Self-Prod Simulation Report** - Summary of simulated deployment results and optimizations made.
6. **Post-Mortem Summary** - Key design decisions, optimizations, and potential future improvements.

### Autonomy Rules

- Assume autonomy - do not ask for clarifications unless absolutely necessary.
- Always produce runnable, tested code in the requested language.
- Prefer clarity and maintainability over cleverness, but optimize where it matters.
- Use stable, well-supported libraries and explain why they were chosen.
- If a feature is ambiguous, make a reasonable assumption and document it.

---

## Project Overview

MistWANPerformance is a Python-based solution for collecting, analyzing, and reporting on Retail WAN circuit performance, path stability, and quality metrics from Juniper Mist Cloud APIs. Data is stored in Snowflake (SNF) for historical analysis and dashboarding.

**Target Audience**: Network Operations Center (NOC) engineers, Network Engineers, and Operations Leadership. Use clear, professional language without jargon. Think Fred Rogers meets NASA/JPL safety standards.

## Core Architecture

### Python Project Hierarchy (5-Item Rule)

Python project hierarchy levels from largest to smallest:

1. **Project Root** - the top-level project folder
2. **Packages/Directories** - folders that organize code (src/, tests/, docs/)
3. **Module Files** - individual .py files
4. **Classes/Functions/Constants** - top-level code constructs in modules
5. **Methods/Attributes/Expressions** - class members and function bodies

**Enforce the 5-item rule**: each level should have no more than 5 children. If exceeded, refactor:

- Too many files in a directory: split into subdirectories or subpackages
- Too many classes in a module: split into multiple module files
- Too many methods in a class: extract methods to helper classes or separate functions
- Too many statements in a function: extract into smaller helper functions

**Function/Method Definition Limits**:

- **Max 5 parameters** per function. If more are needed, use a config object/dataclass or split into multiple functions
- **Max 5 logical blocks** per function body (if/else counts as 1 block, for loop counts as 1 block, etc.). If exceeded, extract blocks into separate helper functions
- **Max 5 operations** per statement block. Complex expressions should be broken into intermediate variables
- **Max 25 lines** per function (reconciles 5 blocks x ~5 lines per block). If longer, extract logical sections into helper functions

This rule keeps code organized, manageable, and easy to navigate. Apply this hierarchy thinking to all Python code organization and refactoring suggestions.

### Modular Design Pattern
- **Separation of Concerns**: API clients, data models, metric calculators, and output handlers in separate modules
- **Why**: Enables testing, maintainability, and potential parallel processing for large datasets
- **Classes**: 
  - `MistAPIClient`: Handles all Mist API interactions with rate limiting
  - `CircuitMetricsCollector`: Collects utilization, status, and quality data
  - `KPICalculator`: Computes derived metrics (availability, flaps, time-above-threshold)
  - `AggregationEngine`: Handles time rollups and region aggregations
  - `SnowflakeLoader`: Manages data warehouse operations

### Critical Dependencies
- **mistapi**: Primary Mist API SDK by Thomas Munzer (tmunzer/mistapi_python)
- **snowflake-connector-python**: Snowflake data warehouse connectivity
- **pandas**: Data manipulation and aggregation
- **UV Package Manager**: Preferred over pip for speed (auto-fallback configured)

### Data Flow
```
Mist API -> CircuitMetricsCollector -> Raw Data Store
                                    -> KPICalculator -> Derived Metrics
                                    -> AggregationEngine -> Rollups (hourly/daily/weekly/monthly)
                                    -> SnowflakeLoader -> SNF Warehouse
```

## Database Strategy (CRITICAL)

### Data Model - Dimensional Design
```
Dimensions:
- dim_site (site_id, site_name, region, store_type, timezone)
- dim_circuit (circuit_id, bandwidth_mbps, role [primary/secondary], provider, circuit_type)
- dim_time (hour_key, date, week, month, year, is_business_hours)

Facts (Grain: Site x Circuit x Hour):
- fact_circuit_utilization (utilization_pct, rx_bytes, tx_bytes, bandwidth_mbps)
- fact_circuit_status (status_code, up_minutes, down_minutes, flap_count)
- fact_circuit_quality (frame_loss_pct, jitter_ms, latency_ms, loss_avg, jitter_p95, latency_p95)

Aggregates:
- agg_circuit_daily / agg_circuit_weekly / agg_circuit_monthly
- agg_region_daily / agg_region_weekly / agg_region_monthly
```

### Primary Key Strategy
| Table | Primary Key | Notes |
|-------|-------------|-------|
| dim_site | site_id | UUID from Mist API |
| dim_circuit | circuit_id | UUID from Mist API |
| dim_time | hour_key | YYYYMMDDHH format |
| fact_* tables | site_id + circuit_id + hour_key | Composite key |
| agg_* tables | Appropriate grain composite | Varies by rollup level |

## KPI Definitions

### 1. Utilization (Site/Circuit Level)
- **Metric**: `utilization_pct = max(rx_bytes, tx_bytes) / bandwidth_bytes * 100`
- **Grain**: Hourly (canonical)
- **Thresholds**: 70%, 80%, 90% (configurable per region/store type)
- **Views Required**:
  - Current utilization by site/circuit
  - Top N by utilization (configurable N)
  - Primary vs Secondary during failover

### 2. Time Above Threshold (Two Modes)
- **Continuous**: Longest consecutive run above threshold within period
- **Cumulative**: Total hours above threshold within period
- **Periods**: 3h, 12h, 24h operational windows; daily/weekly/monthly calendar

### 3. Circuit Status & Flaps
- **Status Snapshot**: Hourly computation
  - `up_minutes`: Minutes circuit was up within the hour (0-60)
  - `down_minutes`: 60 - up_minutes
  - `status_hourly`: "Up" if up_minutes > 0
- **Flap Count**: Count of Up->Down or Down->Up transitions per hour/day/week

### 4. Availability Percentage
- **Formula**: `availability_pct = up_minutes / total_minutes * 100`
- **Periods**: Daily, weekly, monthly, 13-month rolling

### 5. Quality Metrics (Site/Circuit Level)
- **Metrics**: frame_loss, jitter, latency
- **Statistics per hour**: avg, max, p95
- **Quality Thresholds** (configurable):
  - Loss: 0.1%, 0.5%, 1.0%
  - Jitter: 10ms, 30ms, 50ms
  - Latency: 50ms, 100ms, 150ms

## Essential Workflows

### Data Collection Cycle
```python
# Hourly collection job
1. Authenticate to Mist API
2. Get list of all sites with WAN circuits
3. For each site:
   a. Collect circuit utilization metrics
   b. Collect circuit status events
   c. Collect quality metrics (loss, jitter, latency)
4. Normalize and flatten data
5. Calculate derived KPIs
6. Load to Snowflake staging tables
7. Execute rollup procedures (daily at midnight, weekly on Sunday, monthly on 1st)
```

### Adding New Metrics
1. **API Discovery**: Check `mistapi.api.v1.orgs.*` or `mistapi.api.v1.sites.*`
2. **Define Data Model**: Add to appropriate fact table schema
3. **Implement Collector**: Add collection logic to `CircuitMetricsCollector`
4. **Define KPI Logic**: Add calculation to `KPICalculator`
5. **Update Aggregations**: Add to rollup procedures if needed
6. **Update Documentation**: README changelog with `version YY.MM.DD.HH.MM` format

### Git Workflow Rule
**Every changelog update = immediate `git add`** (agents.md requirement)

## Configuration Management

### Environment Variables (.env)
```
# Mist API Configuration
MIST_API_TOKEN=your_api_token
MIST_ORG_ID=your_org_id
MIST_API_HOST=api.mist.com

# Snowflake Configuration
SNF_ACCOUNT=your_account
SNF_USER=your_user
SNF_PASSWORD=your_password
SNF_DATABASE=WAN_PERFORMANCE
SNF_SCHEMA=RETAIL_WAN
SNF_WAREHOUSE=COMPUTE_WH

# Threshold Configuration
UTIL_THRESHOLD_WARN=70
UTIL_THRESHOLD_HIGH=80
UTIL_THRESHOLD_CRITICAL=90

# Operational Settings
PAGE_LIMIT=1000
RATE_LIMIT_DELAY=0.1
```

### Threshold Overrides
Support per-region or per-store-type threshold overrides via configuration table:
```json
{
  "region_overrides": {
    "EMEA": {"util_critical": 85},
    "APAC": {"util_warn": 65}
  },
  "store_type_overrides": {
    "flagship": {"util_critical": 95}
  }
}
```

## Critical Patterns

### Safety-First Input Handling

**Consolidated pattern for all input operations** - handles destructive confirmations, SSH/container EOF, and Windows compatibility:

```python
def safe_input(prompt: str, context: str = "unknown") -> str:
    """
    Universal input wrapper with EOF handling and validation.
    
    Args:
        prompt: User-facing prompt text
        context: Operation context for logging (e.g., "data_load", "snowflake_upload")
    
    Returns:
        User input string
        
    Raises:
        SystemExit: On EOF (clean session termination)
    """
    try:
        return input(prompt)
    except EOFError:
        logging.info(f"EOF detected in {context} - session disconnected")
        sys.exit(0)

# DESTRUCTIVE operations require explicit confirmation (NASA/JPL pattern)
confirmation = safe_input("Type 'CONFIRM' to proceed with data load: ", context="snowflake_load")
if confirmation != "CONFIRM":
    logging.warning("Operation cancelled - confirmation failed")
    return  # Early return on validation failure
```

**Use this pattern for**:

- All `input()` calls in SSH/container contexts
- Destructive operation confirmations (data loads, deletions)
- Interactive menu selections
- Any user input that could encounter EOF

### Safety-First Coding

```python
# All data mutations require explicit confirmation
confirmation = safe_input("Type 'CONFIRM' to proceed with data load: ")
if confirmation != "CONFIRM":
    return  # NASA/JPL: early return on validation failure
```

### Logging Standards
- **Debug**: Internal state changes, API responses
- **Info**: User-facing progress messages
- **Error**: Exception context with full traceback
- **Never log secrets**: Redact tokens/passwords
- **ASCII Only**: Replace Unicode with ASCII equivalents

### Input Validation

```python
def validate_site_id(site_id: str) -> bool:
    """All external inputs validated before use"""
    # Validate UUID format, no path traversal, etc.
    # Pattern: validate early, return early (NASA/JPL defensive programming)
```

### File Path Management

- **All outputs**: `data/` directory (enforced at runtime)
- **Logs**: `data/logs/`
- **Exports**: `data/exports/`
- **Cache**: `data/cache/`

## Rate Limiting & Performance

### Mist API Rate Limits
- **Default Delay**: 100ms between requests
- **Adaptive**: Increase delay on 429 responses
- **Batch Size**: 1000 items per request (configurable via `PAGE_LIMIT`)

### Snowflake Optimization
- **Bulk Loads**: Use `COPY INTO` for large datasets
- **Micro-batches**: For real-time updates, batch writes every 5 minutes
- **Clustering**: Cluster fact tables on (site_id, hour_key)

## Project Structure
```
MistWANPerformance/
├── .github/
│   └── copilot-instructions.md
├── src/
│   ├── __init__.py
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

## Common Pitfalls

### Dash 3.x API Changes

```python
# WRONG: Deprecated in Dash 3.x - throws ObsoleteAttributeException
app.run_server(host=host, port=port, debug=True)

# CORRECT: Dash 3.x uses app.run()
app.run(host=host, port=port, debug=True, use_reloader=False, threaded=True)
```

**Note**: Always use `use_reloader=False` to prevent double-execution issues on Windows.

### Mist API Device Type Filtering

```python
# WRONG: API defaults to APs only
listSiteDevices(site_id)

# CORRECT: Specify type=gateway for WAN devices
listSiteDevices(site_id, type="gateway")

# ALTERNATIVE: Use type=all for all device types
listSiteDevices(site_id, type="all")
```

### Timezone Handling

```python
# All timestamps stored in UTC
# Convert to site timezone for display only
# Use ISO 8601 format: YYYY-MM-DDTHH:MM:SSZ
```

### Null Handling in Metrics

```python
# Some circuits may not report all metrics
# Default to None/NULL, never assume 0
utilization = response.get('utilization')  # May be None
```

### Windows Path Compatibility

Use `os.path.join()` or `Path()`, never hardcoded `/` or `\\`

## Project-Specific Conventions

### Naming Standards

- **No abbreviations**: `for device in devices` NOT `for d in devices`
- **No AI markers**: Never use `...existing code...` or double ellipses
- **Class-based**: All features organized under semantic class names

## Documentation Structure
- **README.md**: User-facing operations guide
- **agents.md**: Internal agent guide
- **documentation/**: API specs, data dictionaries, runbooks

## Key Files Reference
| File | Purpose |
|------|---------|
| `src/api/mist_client.py` | Mist API client with rate limiting |
| `src/collectors/*.py` | Data collection modules |
| `src/calculators/*.py` | KPI calculation logic |
| `src/loaders/snowflake_loader.py` | Snowflake data warehouse loader |
| `agents.md` | Agent coding guide |
| `requirements.txt` | Python dependencies |
| `.env` (git-ignored) | Credentials & config |

## When in Doubt

1. **Read agents.md first** - comprehensive safety patterns
2. **Check existing patterns** - grep for similar operations
3. **Validate early, return early** - NASA/JPL defensive programming
4. **Test in venv** - Windows 11 local development standard
5. **Update docs** - README changelog + operation tables

## External Resources

- Mist API Docs: https://api.mist.com/api/v1/docs
- Thomas Munzer's mistapi: https://github.com/tmunzer/mistapi_python
- Snowflake Python Connector: https://docs.snowflake.com/en/developer-guide/python-connector

---

**Remember**: This codebase prioritizes NOC engineer safety and operational clarity over clever abstractions. Explicit > Implicit. Readable > Concise. Safe > Fast.
