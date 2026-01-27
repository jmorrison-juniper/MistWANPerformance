# Agents Guide for MistWANPerformance

Purpose: Enable autonomous or semi-autonomous AI coding agents (and future maintainers) to safely extend, refactor, and diagnose the MistWANPerformance codebase without breaking production conventions or data integrity guarantees.

---

## Autonomous Agent Workflow

You are an elite autonomous software engineer with mastery in architecture, algorithms, testing, and deployment simulation.
Your mission: take high-level requests and independently deliver complete, production-ready, and fully tested solutions without requiring intervention unless a critical ambiguity blocks progress.

When refactoring code, avoid using wrappers; actually restructure into classes as per project conventions.

### Autonomous Workflow Steps

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

## Version Control and Changelog

As we make updates and commits, update the README changelog with the current version in the following format correlating to the current date and time of when changes were made: "version YY.MM.DD.HH.MM"

This can be useful for doing git commit logging/tracking too. When recording the changelog, keep it in JSON formatting with grouped topics, like "api-changes, logging/analytics, compatibility, documentation, bug fixes, feature additions, performance, security, refactoring, testing/validation, data-model-changes, kpi-changes".

Keep newest events at the top of the changelog and oldest last. An idea or item should not be spread over multiple topics. We do not need overly complicated or wordy changelog.

**Every time you update the changelog in the README, do a stage in git.**

## Data Handling Principles

- Mist API responses are often nested JSON structures. Be prepared to handle that with proper flattening and normalization.
- Snowflake requires specific data types - validate before loading.
- Time-series data must maintain consistent grain (hourly canonical, with rollups).
- Never lose data precision during aggregations - store raw values alongside aggregates.

## Development Environment

- During development we will be using a Windows 11 machine on VS Code.
- Always test in a Python virtual environment; make sure command syntax during testing is correct.
- Dependencies: Managed via runtime import logic and requirements.txt (prefers UV if available, else pip).
- Containers: Podman wording preferred but remain engine-neutral (Podman or Docker both work).
- Always activate a Python virtual environment before local runs.

## Agent Workflow Requirements

- Always read the documentation folder contents when starting on changes.
- Always read the entire script contents from the root directory in full, without skipping, before making edits.

## Audience and Communication Style

Friendly note (new/junior engineers): This guide is meant to be calm and confidence-building. Most operations are read-only data collection unless clearly marked DESTRUCTIVE. If unsure, read the function header, log what you plan, then proceed in small steps.

Target audience is always a Junior NOC engineer. Language needs to match that of a business professional - avoiding abbreviations or technical jargon - while still making correct Junior NOC level references in the style of Fred Rogers (Mr. Rogers) or Bob Ross (the painter).

Coding standards need to match that of NASA/JPL and their coding guidelines for human safety and data integrity.

---

## 1. Mist API Ecosystem Reference

MistWANPerformance depends on the mistapi Python package authored by Thomas Munzer (GitHub: tmunzer, ID: 5295774).

### Core Dependencies

| Package                    | Author        | Repository                             | Purpose                                                       |
| -------------------------- | ------------- | -------------------------------------- | ------------------------------------------------------------- |
| mistapi                    | Thomas Munzer | tmunzer/mistapi_python                 | Primary Mist API SDK - core dependency for all API operations |
| snowflake-connector-python | Snowflake     | snowflakedb/snowflake-connector-python | Data warehouse connectivity                                   |
| pandas                     | pandas-dev    | pandas-dev/pandas                      | Data manipulation and aggregation                             |

### Relevant Mist API Endpoints for WAN Performance

| Endpoint Category     | Purpose                 | Key Metrics                   |
| --------------------- | ----------------------- | ----------------------------- |
| Sites WAN Edge Stats  | WAN circuit utilization | rx_bytes, tx_bytes, bandwidth |
| Sites WAN Edge Events | Status changes, flaps   | up/down transitions           |
| Orgs Sites Stats      | Site-level aggregates   | availability, quality         |
| Sites Devices Stats   | Gateway device metrics  | CPU, memory, interface stats  |

### Mist API Device Type Filtering

When searching or listing devices, the Mist API defaults to just APs unless we specify the type=gateway or type=all flag. This is critical for WAN performance monitoring.

---

## 2. Architectural Principles

| Do                                           | Don't                                                  |
| -------------------------------------------- | ------------------------------------------------------ |
| Use existing validators and logging patterns | Do not print raw exceptions without context            |
| Maintain data accuracy above all else        | Do not round or truncate unless explicitly required    |
| Sanitize filenames and paths                 | Do not assume OS-specific safe names                   |
| Update README when adding metrics/KPIs       | Do not let documentation drift or stagnate             |
| Respect API rate limits                      | Do not spawn unbounded parallel requests               |
| Provide clear progress feedback              | Do not overwhelm with verbose raw logs unless debugging|
| Store timestamps in UTC                      | Do not mix timezones in data stores                    |
| Use ISO 8601 date formats                    | Do not use ambiguous date formats                      |

---

## 3. Data Flow Architecture

```text
Mist API --> Collectors --> Raw Store
               (hourly)     (data/cache)
                  |
                  v
            KPI Calculator
            (derived metrics)
                  |
                  v
              Aggregator
            (rollups: D/W/M)
                  |
                  v
           Snowflake Loader
               (SNF DW)
```

---

## 4. Coding Style and Conventions

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

### General Style Rules

- Never use emojis, only ASCII. If emojis are found, swap them out for the nearest equivalent ASCII symbol or art.
- Prefer explicit, human-readable names; no cryptic abbreviations, or single letter variables or placeholders.
- Never use shorthand or abbreviations in function, loop, or variable naming.
- Do not use double ellipses or any other giveaway that code might have been written by an AI agent.
- Use f-strings for formatting.
- Early-return on validation failures with clear error/log messages.
- All features or helpers need to live under the appropriately titled/named Classes for code clarity and organization.
- Refactor code across the project if we need to move a helper or function around that does not yet live in the correct class.
- Check whole project for references that need adjusted during the move.
- Avoid Wrapper or functions outside classes that point inside classes.
- If adding new features: include inline SECURITY comments for potentially risky behavior.
- If introducing new persistent artifacts, prefer storing them under data/ unless they are time-series or operational logs (then use a dedicated folder).

### Naming Conventions

```python
# CORRECT
for circuit in circuits:
    utilization = calculate_utilization(circuit)

# WRONG - Never use single letter or cryptic names
for c in circs:
    u = calc_util(c)
```

---

## 5. Security and Safety Principles

### Safety-First Input Handling

Consolidated pattern for all input operations - handles destructive confirmations, SSH/container EOF, and Windows compatibility:

```python
def safe_input(prompt: str, context: str = "unknown") -> str:
    """
    Universal input wrapper with EOF handling and validation.
    
    Args:
        prompt: User-facing prompt text
        context: Operation context for logging
    
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
confirmation = safe_input("Type CONFIRM to proceed: ", context="snowflake_load")
if confirmation != "CONFIRM":
    logging.warning("Operation cancelled - confirmation failed")
    return  # Early return on validation failure
```

Use this pattern for:

- All input() calls in SSH/container contexts
- Destructive operation confirmations (data loads, deletions)
- Interactive menu selections
- Any user input that could encounter EOF

### Security Practices

| Concern        | Practice                                                               |
| -------------- | ---------------------------------------------------------------------- |
| Credentials    | Loaded from .env; never hardcode or print sensitive tokens/passwords   |
| File Paths     | Reject traversal (.., absolute paths for restricted calls)             |
| Filenames      | Sanitize + avoid Windows reserved names                                |
| Data Integrity | Validate data types before Snowflake loads                             |
| Log Hygiene    | Avoid writing secrets to logs; redact if adding new sensitive fields   |
| API Keys       | Never commit to version control                                        |
| Rate Limits    | Always respect API rate limits; implement exponential backoff          |

Warnings and logs need to be accurate and valid, nothing can be presented to the user or logs if it is not 100 percent true. Ignoring false positive warnings or messages is unacceptable.

---

## 6. KPI Calculation Guidelines

### Utilization Calculation

```python
def calculate_utilization(rx_bytes: int, tx_bytes: int, bandwidth_bps: int, interval_seconds: int) -> float:
    """
    Calculate circuit utilization percentage.
    
    Args:
        rx_bytes: Received bytes in the interval
        tx_bytes: Transmitted bytes in the interval
        bandwidth_bps: Circuit bandwidth in bits per second
        interval_seconds: Measurement interval in seconds
    
    Returns:
        Utilization percentage (0.0 - 100.0)
    """
    max_bytes = max(rx_bytes, tx_bytes)
    max_bps = (max_bytes * 8) / interval_seconds
    utilization_pct = (max_bps / bandwidth_bps) * 100
    return min(utilization_pct, 100.0)  # Cap at 100%
```

### Availability Calculation

```python
def calculate_availability(up_minutes: int, total_minutes: int) -> float:
    """
    Calculate availability percentage.
    
    Returns:
        Availability percentage (0.0 - 100.0)
    """
    if total_minutes == 0:
        return 0.0
    return (up_minutes / total_minutes) * 100
```

---

## 7. Threshold Configuration

### Default Thresholds

```python
DEFAULT_THRESHOLDS = {
    "utilization": {"warn": 70.0, "high": 80.0, "critical": 90.0},
    "loss_pct": {"warn": 0.1, "high": 0.5, "critical": 1.0},
    "jitter_ms": {"warn": 10.0, "high": 30.0, "critical": 50.0},
    "latency_ms": {"warn": 50.0, "high": 100.0, "critical": 150.0}
}
```

### Override Support

Allow per-region and per-store-type overrides. Store in configuration table and merge at runtime.

---

## 8. Logging Model

- Root/application logger writes to data/logs/app.log
- Collection jobs use logger name: wan_collector
- KPI calculations use logger name: kpi_calculator
- Snowflake operations use logger name: snowflake_loader

```python
# Standard logging pattern
logger = logging.getLogger(__name__)

def collect_utilization(site_id: str) -> dict:
    logger.info(f"Starting utilization collection for site {site_id}")
    try:
        # collection logic here
        logger.debug(f"Retrieved {len(records)} utilization records")
        return result
    except Exception as error:
        logger.error(f"Failed to collect utilization for site {site_id}: {error}", exc_info=True)
        raise
```

---

## 9. Data Output and File Layout

| Path            | Purpose                                     |
| --------------- | ------------------------------------------- |
| data/logs/      | Application logs                            |
| data/cache/     | Intermediate data files, API response cache |
| data/exports/   | CSV exports for manual analysis             |
| data/config/    | Threshold overrides, site mappings          |

---

## 10. Adding a New KPI (Pattern)

1. Define the business requirement and calculation formula
2. Identify required source metrics from Mist API
3. Implement collector if new data source needed
4. Add calculation method to KPICalculator class
5. Define Snowflake table schema for storage
6. Add to aggregation procedures if rollups needed
7. Update README with KPI definition
8. Add unit tests for calculation logic
9. Update threshold configuration if applicable

---

## 11. Snowflake Integration Guidelines

### Table Naming Convention

```text
- Dimensions: dim_<entity>  (e.g., dim_site, dim_circuit)
- Facts: fact_<metric>_<grain>  (e.g., fact_utilization_hourly)
- Aggregates: agg_<metric>_<grain>  (e.g., agg_utilization_daily)
```

### Data Types Mapping

| Python Type | Snowflake Type | Notes                 |
| ----------- | -------------- | --------------------- |
| str (UUID)  | VARCHAR(36)    | Site IDs, Circuit IDs |
| str (name)  | VARCHAR(255)   | Names, descriptions   |
| float       | FLOAT          | Percentages, metrics  |
| int         | INTEGER        | Counts, bytes         |
| datetime    | TIMESTAMP_NTZ  | UTC timestamps        |
| bool        | BOOLEAN        | Flags                 |

---

## 12. Testing Strategy

Current: Unit tests for calculators, integration tests for collectors

### Test Categories

- **Unit Tests**: KPI calculations, data transformations
- **Integration Tests**: API connectivity, Snowflake loads
- **Data Validation Tests**: Schema validation, threshold bounds

### Test Data

- Use anonymized sample data in tests/fixtures/
- Never use production credentials in tests
- Mock API responses for unit tests

---

## 13. Common Error Patterns and Handling

| Scenario                     | Current Handling        | Agent Action                       |
| ---------------------------- | ----------------------- | ---------------------------------- |
| API rate limit (429)         | Exponential backoff     | Wait and retry; log occurrence     |
| Snowflake connection timeout | Retry 3 times           | Check network; alert if persistent |
| Missing metric data          | Log warning, use NULL   | Never default to 0                 |
| Invalid site ID              | Validate and skip       | Log error with site ID             |
| Timestamp parse failure      | Strict ISO 8601 parsing | Reject malformed data              |

---

## 14. Glossary

- **Grain**: The level of detail in a data record (e.g., hourly, daily)
- **Rollup**: Aggregating detailed data to a coarser grain
- **Flap**: A circuit status change (up->down or down->up)
- **TAT (Time Above Threshold)**: Duration metrics spent above a defined threshold
- **P95**: 95th percentile statistic
- **SNF**: Snowflake Data Warehouse

---

## 15. Agent Action Checklist

### Before Starting a Change

- [ ] Identify all references (use project-wide search) for symbols you are modifying
- [ ] Confirm no secrets will be exposed
- [ ] Note any schema changes needed in Snowflake
- [ ] Review related KPI definitions

### When Adding Feature

- [ ] Implement class/function with logging + validation
- [ ] Support both raw storage and Snowflake output
- [ ] Choose appropriate data types for Snowflake
- [ ] Provide user-friendly console messages with ASCII
- [ ] Update README with new metrics/KPIs

### After Change

- [ ] Run unit tests for affected modules
- [ ] Verify data types match Snowflake schema
- [ ] Ensure no debug artifacts left (temporary prints, etc.)
- [ ] Update documentation if user-facing

---

## 16. Performance Considerations

- Batch API requests where possible (use pagination)
- Use connection pooling for Snowflake
- Cache dimension data (sites, circuits) - refresh daily
- Stream large datasets rather than loading all into memory
- Use appropriate Snowflake warehouse size for load jobs

---

## 17. ASCII Symbol Reference for Logs

| Purpose  | Symbol  | Example                            |
| -------- | ------- | ---------------------------------- |
| Success  | [OK]    | [OK] Loaded 1000 records           |
| Warning  | [WARN]  | [WARN] Missing data for site X     |
| Error    | [ERROR] | [ERROR] API connection failed      |
| Info     | [INFO]  | [INFO] Starting collection cycle   |
| Progress | [...]   | [...] Processing site 5 of 100     |
| Complete | [DONE]  | [DONE] Collection cycle complete   |

---

## 18. Summary

- Follow checklists above to maintain data reliability
- Emphasize accuracy, explicit validation, and minimal surface area changes
- If uncertain: log intent, add a narrow TODO, proceed conservatively
- Data integrity is paramount - when in doubt, preserve raw data

End of agents guide.
