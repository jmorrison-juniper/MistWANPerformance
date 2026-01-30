# MistWANPerformance - TODO

## High Priority

### Site-Level SLE Deep-Dive Data Collection

**Status:** Completed (Tasks F1-F4 Complete)  
**Started:** 2026-01-29  
**Completed:** 2026-01-30

**Goal:** Collect detailed site-level SLE data for degraded sites. Use org-level API to identify degraded sites, then fetch detailed diagnostics only for those sites. Smart time-series fetching with 10-minute resolution across 7 days, using incremental fetching when historical data exists.

---

#### Raw Endpoint Reference (Provided by User)

| Endpoint | Method | Scope | Purpose |
| -------- | ------ | ----- | ------- |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/threshold` | `getSiteSleThreshold` | Site | Get SLE threshold config |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/summary` | `getSiteSleSummary` | Site | Get SLE summary with classifiers (time-series) |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/histogram` | `getSiteSleHistogram` | Site | Get histogram distribution |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/impact-summary` | `getSiteSleImpactSummary` | Site | Get impact summary counts |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/impacted-clients` | `listSiteSleImpactedWirelessClients` | Site | Get impacted clients list |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/impacted-peer-paths` | N/A (not in mistapi) | Site | Get impacted peer paths |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/impacted-gateways` | `listSiteSleImpactedGateways` | Site | Get impacted gateways list |
| `/sites/{site_id}/sle/site/{site_id}/metric/{metric}/impacted-interfaces` | `listSiteSleImpactedInterfaces` | Site | Get impacted interfaces list |

---

#### Org-Level vs Site-Level Strategy

**Org-Level (Already Implemented):**

- `getOrgSitesSle(sle="wan")` - SLE scores for all sites (gateway-health, wan-link-health, application-health)
- `getOrgSle(metric="worst-sites-by-sle")` - Worst performing sites list

**Site-Level (New - For Degraded Sites Only):**

- Use org-level API to identify sites with SLE < 90%
- Fetch detailed site-level diagnostics ONLY for degraded sites
- Reduces API calls from 3,208 sites to ~100-200 degraded sites

---

#### API Testing Results (2026-01-29)

**getSiteSleHistogram Response:**

```json
{
  "metric": "wan-link-health-v2",
  "start": 1769660273,
  "end": 1769746673,
  "data": [
    {"range": [null, 0], "value": 0},
    {"range": [0.0, 5.0], "value": 98916.0},
    {"range": [5.0, 10.0], "value": 0}
  ]
}
```

**getSiteSleSummary Response (Time-Series):**

```json
{
  "start": 1769660283,
  "end": 1769746683,
  "sle": {
    "name": "wan-link-health",
    "interval": 3600,
    "samples": {
      "total": [50.77, 44.87, 38.83, ...],
      "degraded": [0.0, 3.0, 0.0, ...]
    }
  },
  "impact": {
    "num_users": 0,
    "num_gateways": 1,
    "total_gateways": 1
  },
  "classifiers": [
    {"name": "interface-negotiation-failed", "interval": 3600, "samples": {...}}
  ]
}
```

**listSiteSleImpactedGateways Response:**

```json
{
  "start": 1769660301,
  "end": 1769746701,
  "metric": "wan-link-health",
  "gateways": [
    {
      "gateway_mac": "90ec77710609",
      "name": "1NJR010482G",
      "duration": 601.5,
      "degraded": 38.95,
      "gateway_model": "SSR130",
      "gateway_version": "6.2.6-15.sts"
    }
  ]
}
```

**listSiteSleImpactedInterfaces Response:**

```json
{
  "start": 1769660309,
  "end": 1769746709,
  "interfaces": [
    {
      "interface_name": "ge-0/0/2",
      "gateway_name": "1NJR010482G",
      "gateway_mac": "90ec77710609",
      "duration": 359.02,
      "degraded": 38.95
    }
  ]
}
```

**getSiteSleThreshold Response:**

```json
{
  "metric": "wan-link-health-v2",
  "minimum": 0,
  "maximum": 0,
  "default": 0,
  "units": "Mbps",
  "direction": "right",
  "threshold": 0
}
```

**Available WAN-Link-Health Classifiers:**

- `interface-negotiation-failed`
- `interface-port-down`
- `interface-vpn`
- `isp-reachability-dhcp`
- `network-vpn-path-down`
- `interface-cable-issues`
- `network-loss`
- `network-jitter`
- `isp-reachability-arp`
- `interface-lte-signal`
- `interface-congestion`
- `network-latency`

---

#### Implementation Tasks

##### Task F1: MistAPIClient Site-Level SLE Methods

- [x] Add `get_site_sle_summary(site_id, metric, start, end, duration)` to MistAPIClient
- [x] Add `get_site_sle_histogram(site_id, metric, start, end, duration)` to MistAPIClient
- [x] Add `get_site_sle_threshold(site_id, metric)` to MistAPIClient
- [x] Add `get_site_sle_impacted_gateways(site_id, metric, start, end)` to MistAPIClient
- [x] Add `get_site_sle_impacted_interfaces(site_id, metric, start, end)` to MistAPIClient
- [x] Support smart start_time from cached last timestamp for incremental fetching

##### Task F2: Redis Storage Schema for Site-Level SLE

- [x] Design key patterns:
  - `mistwan:site_sle:{site_id}:summary:{metric}` - Summary time-series
  - `mistwan:site_sle:{site_id}:histogram:{metric}` - Histogram data
  - `mistwan:site_sle:{site_id}:impacted_gateways:{metric}` - Impacted gateways
  - `mistwan:site_sle:{site_id}:impacted_interfaces:{metric}` - Impacted interfaces
  - `mistwan:site_sle:{site_id}:threshold:{metric}` - Threshold config
  - `mistwan:site_sle:last_fetch:{site_id}` - Last fetch timestamp for incremental
- [x] Add save methods: `save_site_sle_summary()`, `save_site_sle_histogram()`, etc.
- [x] Add get methods: `get_site_sle_summary()`, `get_site_sle_histogram()`, etc.
- [x] Add `get_last_site_sle_timestamp(site_id)` for incremental fetching
- [x] TTL: 7 days for all site-level SLE data

##### Task F3: Degraded Site Collection Workflow

- [x] Create `SLECollector` class in `src/collectors/sle_collector.py`:
  - `collect_for_site()` - Collect all SLE data for a single site
  - `collect_for_degraded_sites()` - Priority collection for degraded sites
  - `collect_for_all_sites()` - Background collection with cache freshness check
- [x] Create `SLEBackgroundWorker` class in `src/cache/background_refresh.py`:
  - Phase 1: Collect degraded sites first (priority)
  - Phase 2: Collect all sites incrementally
  - Rate limiting: 2 seconds between site API calls
  - Integration with run_dashboard.py background workers
- [x] Add `get_site_sle_details()` method to `DashboardDataProvider`

##### Task F4: Dashboard Integration

- [x] Add "Site Details" drill-down view when clicking degraded site row
- [x] Display SLE summary time-series chart
- [x] Display histogram as bar chart
- [x] List impacted gateways and interfaces in tables
- [x] Show classifier breakdown (network-loss, jitter, latency, etc.)

---

### Async/Parallel Optimization Plan

**Status:** Completed  
**Started:** 2026-01-29  
**Completed:** 2026-01-30

**Goal:** Improve performance by applying async I/O and parallel processing patterns where appropriate.

**Analysis Summary:**

| Module | Type | Current State | Recommended Optimization |
| ------ | ---- | ------------- | ------------------------ |
| `run_dashboard.py` | Mixed | ThreadPoolExecutor | Already parallel (no change) |
| `redis_cache.py` | I/O-bound | sync redis loops | Redis Pipeline for bulk ops |
| `kpi_calculator.py` | CPU-bound | single-threaded | ProcessPoolExecutor option |
| `time_aggregator.py` | CPU-bound | single-threaded | ProcessPoolExecutor option |
| `background_refresh.py` | I/O-bound | threading | asyncio TaskGroup (future) |
| `mist_client.py` | I/O-bound | sync paged | asyncio (future, high effort) |

---

### Implementation Order (Lowest Effort First)

#### Task 1: Redis Pipeline for Bulk Operations

- [x] **Status:** Completed (2026-01-29)
- **Effort:** Low
- **Impact:** Medium (5-10x faster bulk reads)
- **Files:** `src/cache/redis_cache.py`, `run_dashboard.py`, `src/cache/background_refresh.py`
- **Changes:**
  - [x] Refactored `get_all_site_port_stats()` to use pipeline internally
  - [x] Added `get_stale_site_ids_pipelined()` using Redis pipeline
  - [x] Added `get_sites_sorted_by_cache_age_pipelined()` using Redis pipeline
  - [x] Updated `run_dashboard.py` to use pipelined versions with fallback
  - [x] Updated `background_refresh.py` to use pipelined versions with fallback
  - [x] Added NullCache stubs for new pipelined methods
  - [x] Tested: Dashboard starts and runs without errors

#### Task 2: ProcessPoolExecutor for KPI Bulk Calculations

- [x] **Status:** Completed (2026-01-30)
- **Effort:** Low
- **Impact:** Medium (parallel CPU work for large datasets)
- **Files:** `src/calculators/kpi_calculator.py`
- **Changes:**
  - [x] Added `calculate_availability_bulk()` with ProcessPoolExecutor
  - [x] Added `create_daily_aggregates_parallel()` with ProcessPoolExecutor
  - [x] Added worker functions for serializable parallel processing
  - [x] Original methods preserved for backward compatibility

#### Task 3: ProcessPoolExecutor for Time Aggregator

- [x] **Status:** Completed (2026-01-30)
- **Effort:** Low
- **Impact:** Medium (parallel aggregation)
- **Files:** `src/aggregators/time_aggregator.py`, `src/aggregators/__init__.py`, `tests/test_time_aggregator.py`
- **Changes:**
  - [x] Added `aggregate_daily_to_weekly_parallel()` with ProcessPoolExecutor
  - [x] Added `aggregate_daily_to_monthly_parallel()` with ProcessPoolExecutor
  - [x] Added `aggregate_to_region_parallel()` with ProcessPoolExecutor
  - [x] Added `_merge_aggregates_worker()` for serializable parallel processing
  - [x] Added 4 unit tests for parallel aggregation validation
  - [x] Original class methods preserved for backward compatibility

#### Task 4: Background Refresh Async

- [x] **Status:** Completed (2026-01-30)
- **Effort:** Medium
- **Impact:** High (parallel site refresh)
- **Files:** `src/cache/background_refresh.py`, `src/cache/__init__.py`, `tests/test_background_refresh.py`, `requirements.txt`
- **Changes:**
  - [x] Added `AsyncBackgroundRefreshWorker` class with asyncio-based refresh loop
  - [x] Added `refresh_stale_sites_parallel()` using asyncio.TaskGroup for structured concurrency
  - [x] Uses `asyncio.sleep()` instead of blocking sleep
  - [x] Runs blocking API calls in executor to avoid blocking event loop
  - [x] Semaphore-based concurrency limiting (default: 5 parallel refreshes)
  - [x] Updated `__init__.py` to export new async classes
  - [x] Added 12 unit tests for background refresh (async and legacy)
  - [x] Added pytest-asyncio dependency for async test support
  - [x] Legacy `BackgroundRefreshWorker` preserved for backward compatibility

#### Task 5: Mist API Client Async

- [x] **Status:** Completed (2026-01-30)
- **Effort:** High
- **Impact:** High (parallel API calls)
- **Files:** `src/api/async_mist_client.py`, `src/api/__init__.py`, `src/cache/background_refresh.py`, `tests/test_async_mist_client.py`, `requirements.txt`
- **Changes:**
  - [x] Added `AsyncMistConnection` class with aiohttp.ClientSession management
  - [x] Added `AsyncMistStatsOperations` with async port stats fetching
  - [x] Added `AsyncMistAPIClient` facade for unified async API access
  - [x] Uses `aiohttp>=3.9.0` for true async HTTP (added to requirements.txt)
  - [x] Async rate limiting using `asyncio.sleep()` instead of blocking sleep
  - [x] Async retry logic with exponential backoff
  - [x] 429 rate limit handling shared with sync client via `RateLimitState`
  - [x] Updated `AsyncBackgroundRefreshWorker` with `use_async_api` parameter
  - [x] Added 13 pytest-asyncio tests for async API client
  - [x] Sync `MistAPIClient` preserved for backward compatibility

---

## Medium Priority

### SLE and Alarms Time-Series Data Collection

**Status:** API Testing Complete  
**Started:** 2026-01-30

**Goal:** Collect WAN SLE metrics, gateway health, and alarms with 10-minute resolution over 7 days. Use smart time-series handling to only pull incremental data.

---

#### API Testing Results (2026-01-30)

**getOrgSitesSle Response Structure:**

```json
{
  "start": 1769650531,
  "end": 1769736931,
  "limit": 10,
  "page": 1,
  "total": 3208,
  "results": [
    {
      "site_id": "uuid",
      "gateway-health": 1.0,
      "wan-link-health": 0.95,
      "wan-link-health-v2": 0.95,
      "application-health": 0.97,
      "gateway-bandwidth": 1.0,
      "num_gateways": 1,
      "num_clients": 98
    }
  ]
}
```

**getOrgSle (worst-sites-by-sle) Response Structure:**

```json
{
  "start": 1769652000,
  "end": 1769738400,
  "interval": 3600,
  "limit": 10,
  "results": [
    {"site_id": "uuid", "gateway-health": 0.0}
  ]
}
```

**searchOrgAlarms Response Structure:**

```json
{
  "total": 80840,
  "results": [
    {
      "id": "alarm-uuid",
      "site_id": "site-uuid",
      "type": "infra_dhcp_failure",
      "severity": "critical",
      "group": "infrastructure",
      "timestamp": 1769132146,
      "last_seen": 1769132146,
      "incident_count": 20,
      "count": 1
    }
  ]
}
```

**Observed Alarm Types:** `infra_dhcp_failure`, `infra_dns_failure`, `honeypot_ssid`
**Observed Alarm Groups:** `infrastructure`, `security`

---

#### API Endpoints Research

| Endpoint | mistapi Method | Scope | Purpose |
| -------- | -------------- | ----- | ------- |
| `/api/v1/orgs/{org_id}/insights/sites-sle` | `mistapi.api.v1.orgs.insights.getOrgSitesSle()` | Org | WAN SLE per site (interval param for resolution) |
| `/api/v1/orgs/{org_id}/insights/{metric}` | `mistapi.api.v1.orgs.insights.getOrgSle()` | Org | Worst sites by SLE metric (gateway-health, wan-link-health) |
| `/api/v1/orgs/{org_id}/alarms/search` | `mistapi.api.v1.orgs.alarms.searchOrgAlarms()` | Org | Active/historical alarms by type |
| `/api/v1/sites/{site_id}/sle/site/{site_id}/metric/{metric}/summary-trend` | `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend()` | Site | Per-site SLE time-series (fallback if org-level lacks detail) |

---

#### Raw Endpoint Examples (User Provided)

```text
# Org-level SLE (WAN) with 7-day window
GET /api/v1/orgs/{org_id}/insights/sites-sle?sle=wan&limit=100&start={epoch}&end={epoch}&timeInterval=7d

# Org-level Alarms Search (Marvis group)
GET /api/v1/orgs/{org_id}/alarms/search?group=marvis&limit=1000&start={epoch}&end={epoch}

# Org-level Alarms Search (infrastructure types)
GET /api/v1/orgs/{org_id}/alarms/search?type=loop_detected_by_ap,infra_dhcp_failure,infra_dns_failure,infra_arp_failure&limit=1000&start={epoch}&end={epoch}

# Org-level Worst Sites by Gateway Health
GET /api/v1/orgs/{org_id}/insights/worst-sites-by-sle?sle=gateway-health&start={epoch}&end={epoch}

# Site-level SLE Summary Trend (gateway-health)
GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/gateway-health/summary-trend?start={epoch}&end={epoch}

# Site-level SLE Summary Trend (wan-link-health)
GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/wan-link-health/summary-trend?start={epoch}&end={epoch}

# Site-level SLE Summary Trend (application-health)
GET /api/v1/sites/{site_id}/sle/site/{site_id}/metric/application-health/summary-trend?start={epoch}&end={epoch}
```

---

#### SLE and Alarms Implementation Tasks

##### Task A: Org-Level SLE Data Collection

- [x] Add `get_org_sites_sle()` to `MistAPIClient`
  - Call `mistapi.api.v1.orgs.insights.getOrgSitesSle(sle="wan", interval="10m", duration="7d")`
  - Parameters: start/end epoch, interval for 10-min resolution
- [x] Add `get_org_worst_sites_by_sle()` to `MistAPIClient`
  - Call `mistapi.api.v1.orgs.insights.getOrgSle(metric="worst-sites-by-sle", sle="gateway-health")`
- [x] Smart time-series: `get_last_sle_timestamp()` enables incremental fetching
- [x] Store in Redis with `save_sle_snapshot()` and `save_worst_sites_sle()`

##### Task B: Org-Level Alarms Collection

- [x] Add `search_org_alarms()` to `MistAPIClient`
  - Call `mistapi.api.v1.orgs.alarms.searchOrgAlarms()`
  - Support type filtering (infrastructure alarms)
  - Support group filtering (Marvis alerts)
- [x] Handle pagination with `search_after` for large result sets
- [x] Smart time-series: `get_last_alarms_timestamp()` enables incremental fetching
- [x] Store in Redis with `save_alarms()` and individual alarm keys for deduplication

##### Task C: Site-Level SLE (Fallback)

- [x] Add `get_site_sle_trend()` to `MistAPIClient` (if org-level lacks detail)
  - Call `mistapi.api.v1.sites.sle.getSiteSleSummaryTrend()`
  - Metrics: gateway-health, wan-link-health, application-health
- [x] Only use for specific site deep-dives, not bulk collection
- [x] Added to MistInsightsOperations class with facade delegation

##### Task D: Redis Storage Schema

- [x] Design time-series storage for 10-min resolution
- [x] Key patterns implemented:
  - `mistwan:sle:current` - Current SLE snapshot
  - `mistwan:sle:history` - SLE time-series (sorted set)
  - `mistwan:sle:worst:{metric}` - Worst sites by metric
  - `mistwan:alarms:current` - Current alarms snapshot
  - `mistwan:alarms:id:{alarm_id}` - Individual alarms for deduplication
- [x] TTL: 7 days for SLE/alarms data
- [x] Implemented `get_last_sle_timestamp()` for incremental fetching
- [x] Implemented `get_last_alarms_timestamp()` for incremental fetching
- [x] Added filter methods: `get_alarms_by_type()`, `get_alarms_by_site()`

##### Task E: Dashboard Integration

- [x] Add SLE cards to dashboard (SLE Gateway, SLE WAN Link, SLE App, SLE Degraded)
- [x] Add alarms cards to dashboard (Total Alarms, Critical Alarms)
- [x] Display gateway-health and wan-link-health metrics in dashboard
- [x] Wire up SLE/Alarms loading in `run_dashboard.py` startup sequence
- [x] Added `update_sle_data()`, `update_alarms()`, `get_sle_summary()`, `get_alarms_summary()` to DashboardDataProvider
- [x] SLE shows average health scores across all sites (percentage)
- [x] SLE Degraded shows count of sites with gateway-health below 90%
- [x] Alarms shows total count and critical count from last 24 hours

---

---

## Low Priority

No items yet.

---

## Completed

### Incremental Cache Saves During API Fetch

**Status:** Completed  
**Completed:** 2026-01-28

**Problem (Solved):**  
If the script was interrupted mid-fetch (during the 3-5 minute API collection), all fetched data was lost since it only saved to Redis after completion.

**Solution Implemented:**

- Added `on_batch` callback parameter to `MistAPIClient.get_org_gateway_port_stats()`
- Added incremental save methods to `RedisCache`:
  - `start_fetch_session()` - tracks fetch progress
  - `save_batch_incrementally()` - saves each batch as it arrives
  - `update_fetch_progress()` - tracks batches, records, sites saved
  - `complete_fetch_session()` - marks session done
  - `get_incomplete_fetch_session()` - checks for resumable sessions
  - `_append_site_port_stats()` - merges data across batches
- Updated `run_dashboard.py` to use incremental saves:
  - Each API batch is saved to Redis immediately
  - On restart, recovers data from incomplete sessions
  - Progress tracked via fetch session

**Files Modified:**

- `src/api/mist_client.py` - Added on_batch callback
- `src/cache/redis_cache.py` - Added incremental save methods
- `run_dashboard.py` - Uses incremental saves with callback
