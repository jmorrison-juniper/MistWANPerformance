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

## IV.A Relevant Mist API Endpoints

### WAN SLE (Service Level Experience) APIs

| Endpoint | Purpose | Key Metrics |
| -------- | ------- | ----------- |
| `/api/v1/orgs/{org_id}/insights/sites-sle` | Get Org Sites SLE | `application_health`, `gateway-health`, `wan-link-health`, `num_clients`, `num_gateways` |
| `/api/v1/orgs/{org_id}/insights/{metric}` | Get Org SLE (worst sites, Mx Edges) | Multiple SLE metrics by site |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metrics` | List SLE metrics for scope | `gateway-health`, `application_health`, `wan-link-health` |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/summary` | Get SLE summary | Detailed SLE breakdown |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/histogram` | Get SLE histogram | Time distribution data |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/threshold` | Get SLE threshold | Threshold configuration |

### WAN SLE Impact Analysis APIs

| Endpoint | Purpose |
| -------- | ------- |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/impact-summary` | Get impact summary by classifier |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/impacted-gateways` | List impacted gateways |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/impacted-interfaces` | List impacted interfaces |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/impacted-applications` | List impacted applications |
| `/api/v1/sites/{site_id}/sle/{scope}/{scope_id}/metric/{metric}/classifiers` | Get SLE classifiers |

### WAN Client APIs

| Endpoint | Purpose |
| -------- | ------- |
| `/api/v1/orgs/{org_id}/wan_clients/search` | Search Org WAN Clients |
| `/api/v1/orgs/{org_id}/wan_clients/count` | Count WAN Clients by distinct attributes |
| `/api/v1/orgs/{org_id}/wan_clients/events/search` | Search WAN Client Events |
| `/api/v1/orgs/{org_id}/wan_client/events/count` | Count WAN Client Events |

### Device and Gateway Stats APIs

| Endpoint | Purpose |
| -------- | ------- |
| `/api/v1/sites/{site_id}/stats/devices` | Get site device stats (includes `port_stat`) |
| `/api/v1/sites/{site_id}/stats/devices/{device_id}` | Get specific device stats |
| `/api/v1/sites/{site_id}/stats/gateways/metrics` | Get site gateway metrics (config_success, version_compliance) |

### Constants and Definitions

| Endpoint | Purpose |
| -------- | ------- |
| `/api/v1/const/insight_metrics` | List all available insight metrics |

### WAN SLE Metric Types

The following SLE metrics are specifically relevant for WAN performance:

| Metric | Description |
| ------ | ----------- |
| `gateway-health` | Overall gateway device health score |
| `application_health` | Application performance health score |
| `wan-link-health` | WAN link quality and availability score |

### WAN SLE Impact Fields

For WAN SLE filtering and drilldown, use these fields:

- `gateway` - Filter by gateway device
- `client` - Filter by client
- `interface` - Filter by WAN interface
- `chassis` - Filter by chassis
- `peer_path` - Filter by peer path (for SD-WAN)
- `gateway_zones` - Filter by gateway zones

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

### 5. Mist SLE-Based Health Scores (Site/Circuit Level)

Mist provides pre-computed Service Level Experience (SLE) metrics via API. These complement raw performance metrics:

#### WAN SLE Metrics

| SLE Metric | Description | Use Case |
| ---------- | ----------- | -------- |
| `gateway-health` | Overall gateway device health (0.0-1.0) | Device reliability monitoring |
| `application_health` | Application performance health (0.0-1.0) | End-user experience tracking |
| `wan-link-health` | WAN link quality and availability (0.0-1.0) | Circuit health monitoring |

#### SLE Data Collection

- **Scope**: Can be collected at site, gateway, or client level
- **Time Range**: Supports duration (7d, 2w), interval aggregation (1h, 10m)
- **API Parameters**: `start`, `end`, `duration`, `interval`

#### SLE Views

- Worst performing sites by SLE metric
- Impacted gateways/interfaces during degraded SLE
- Application health correlation with circuit issues
- SLE trends over time (daily, weekly, monthly)

#### SLE Thresholds

Recommended thresholds for SLE scores:

| Level | Score Range | Action |
| ----- | ----------- | ------ |
| Healthy | >= 0.95 | No action |
| Warning | 0.80 - 0.95 | Monitor closely |
| Degraded | 0.60 - 0.80 | Investigate |
| Critical | < 0.60 | Immediate attention |

---

### 6. Aggregations & Time Windows

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
| Executive Overview | Trends, top offenders, SLE health scores                                                    |
| Engineering View   | Live congestion + quality, drill to site/circuit, availability + flaps + chronic offenders  |
| SLE Health View    | Gateway health, application health, WAN link health scores with impact analysis             |

### Drilldowns

- Region -> Site List -> Site Detail -> Circuit Detail -> Time Series
- Exportable "Top Offenders" tables
- SLE Impact Drilldown: Worst SLE -> Impacted Gateways -> Impacted Interfaces -> Root Cause Classifiers
