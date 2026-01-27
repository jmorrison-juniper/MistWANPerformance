# Retail WAN Performance, Path Stability & Quality Visibility

## Reporting Requirements

---

## I. Goal

Provide reliable, historical visibility into Retail WAN circuit performance and "peer/path" stability/quality

---

## II. Audience & Use Cases

### Primary Users

- Network Operations Center (NOC) Engineers
- Network Engineers
- Operations Leadership

### Core Questions

- Which sites/circuits are congested right now and trending worse?
- Which regions/sites have chronic instability (flaps, loss, jitter, latency)?
- How often do circuits failover (primary to secondary), and what is the quality during failover?
- What is the "time above threshold" for congestion and quality issues (continuous vs cumulative)?

---

## III. Scope

- WAN circuit utilization + congestion thresholding
- Circuit status (Up/Down), flaps, availability %
- Quality: frame loss, jitter, latency
- Aggregations: Site/Circuit, Region, time rollups

---

## IV. Data Sources & Storage

| Component | Technology      |
| --------- | --------------- |
| Source    | Mist APIs       |
| Warehouse | Snowflake (SNF) |

---

## V. KPI & Dimensions

### Dimensions

| Dimension | Attributes                                             |
| --------- | ------------------------------------------------------ |
| Site      | site_id, site_name, region                             |
| Circuit   | bandwidth_mbps, role (primary/secondary), active_state |
| Time      | hourly grain canonical; day/week/month rollups         |

### Grain

Site x Circuit x Hour

---

## KPI Definitions

### 1. Utilization (Site/Circuit Level)

#### Time Grain

- Hourly (required)

#### Thresholds (Configurable)

- 70%, 80%, 90%
  - Optional overrides by region/store type

#### Views

- "Current utilization" by site/circuit
- "Top 10 by utilization" (configurable: top N)
- "Primary vs Secondary in failure":
  - When primary is down/unhealthy, utilization should be shown on the active circuit (secondary) AND still preserve primary metrics for comparison

#### Time Above Threshold

Two modes (both required):

| Mode       | Definition                                                                                           |
| ---------- | ---------------------------------------------------------------------------------------------------- |
| Continuous | Longest consecutive run above threshold within a period (e.g., within last 24h / day / week / month) |
| Cumulative | Total hours above threshold within a period                                                          |

#### Rollups

- Daily, weekly, monthly
- Operational windows: last 3h, 12h, 24h

---

### 2. Circuit Status (Up/Down) & Flaps

#### Status Snapshot

Recommended: compute hourly status as:

| Metric        | Description                                     |
| ------------- | ----------------------------------------------- |
| up_minutes    | Minutes within the hour circuit was up (0-60)   |
| down_minutes  | Minutes within the hour circuit was down (0-60) |
| status_hourly | "Up" if up_minutes > 0                          |

#### Flap Count

- Count transitions Up to Down or Down to Up per hour/day/week

---

### 3. Availability %

**Formula**: `availability_pct = (up_minutes / total_minutes) * 100`

---

### 4. Performance Metrics (Site/Circuit Level)

#### Metrics

- Frame loss
- Jitter
- Latency

#### Statistics to Store

For each metric, store at least:

- Hourly average
- Hourly max
- Hourly p95 (recommended for jitter/latency/loss)

#### Quality Thresholds (Configurable)

Define "bad quality" thresholds similar to utilization thresholds

---

### 5. Aggregations & Time Windows

#### By Region

- Required for all metrics

#### By Time

| Category    | Windows                |
| ----------- | ---------------------- |
| Operational | 3h, 12h, 24h           |
| Calendar    | Daily, weekly, monthly |
| Historic    | 13 months              |

---

## Outputs

### Dashboards / Views

| View               | Features                                                                                    |
| ------------------ | ------------------------------------------------------------------------------------------- |
| Executive Overview | Trends, top offenders                                                                       |
| Engineering View   | Live congestion + quality, drill to site/circuit, availability + flaps + chronic offenders  |

### Drilldowns

- Region -> Site List -> Site Detail -> Circuit Detail -> Time Series
- Exportable "Top Offenders" tables

