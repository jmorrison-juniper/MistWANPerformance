# MistWANPerformance - TODO

## High Priority

### Async/Parallel Optimization Plan

**Status:** In Progress  
**Started:** 2026-01-29

**Goal:** Improve performance by applying async I/O and parallel processing patterns where appropriate.

**Analysis Summary:**
| Module | Type | Current State | Recommended Optimization |
|--------|------|---------------|-------------------------|
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
- [ ] **Status:** Not Started
- **Effort:** Low
- **Impact:** Medium (parallel aggregation)
- **Files:** `src/aggregators/time_aggregator.py`
- **Changes:**
  - Add parallel option to `create_daily_aggregates()`
  - Split circuits across workers, merge results

#### Task 4: Background Refresh Async (Future)
- [ ] **Status:** Not Started
- **Effort:** Medium
- **Impact:** High (parallel site refresh)
- **Files:** `src/cache/background_refresh.py`
- **Changes:**
  - Convert to asyncio with TaskGroup
  - Refresh multiple stale sites in parallel
  - Use asyncio.sleep() instead of blocking sleep

#### Task 5: Mist API Client Async (Future)
- [ ] **Status:** Not Started
- **Effort:** High
- **Impact:** High (parallel API calls)
- **Files:** `src/api/mist_client.py`
- **Changes:**
  - Add async versions of API methods
  - Use aiohttp or async mistapi if available
  - Parallel page fetches where possible

---

## Medium Priority

No items yet.

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
