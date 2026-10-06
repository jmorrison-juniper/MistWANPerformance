# MistWANPerformance

## What

MistWANPerformance collects retail wide area network circuit metrics from Juniper
Mist Cloud and provides a dashboard for congestion, availability, and path quality.
Snowflake supports historical reporting; Redis supports dashboard caching.

![Actual dashboard overview with synthetic offline data](docs/screenshots/overview.png)

See [four application screens and their offline capture method](docs/screens.md).
These are real application captures, not live network measurements.

## How

With `uv` and Python 3.13 installed, run these commands from the repository root
to install dependencies and start the [offline preview](docs/screens.md):

```bash
uv sync --frozen --extra dev --python 3.13
uv run --no-sync python -m tests.fixtures.offline_dashboard
```

Open `http://127.0.0.1:8051`. Stop the preview with Ctrl+C.
The preview uses synthetic data and needs no Mist, Snowflake, or Redis connection.
For deployed collection, follow the [installation, configuration, and operating
guide](docs/operations.md#installation). Configure your credentials privately.
Never commit them.

## Where

Application code is in [src/](src/), offline checks in [tests/](tests/), and detailed
guidance in [docs/](docs/operations.md). Runtime logs, exports, and cache files
belong under `data/`. The dashboard defaults to `http://127.0.0.1:8050`.

## When

Use the dashboard during daily monitoring and incident investigation. Metrics use
an hourly reporting grain with daily, weekly, and monthly summaries; timestamps
are stored in UTC. See [metric definitions](docs/operations.md#kpi-definitions)
and [release history](docs/changelog.md).

## Why

Identify congested circuits, unstable paths, and repeated quality problems so
operators can prioritize investigation using consistent measurements.
See [scope and reporting questions](docs/operations.md#core-questions-this-solution-answers).

## Who

For network operations engineers, network engineers, and operations leadership.
Maintained in [jmorrison-juniper/MistWANPerformance](https://github.com/jmorrison-juniper/MistWANPerformance).
Internal use only - Hewlett Packard Enterprise. Contributors should follow
[the repository agent instructions](.github/copilot-instructions.md) and
[offline checks](docs/operations.md#offline-tests-and-dependency-updates).
