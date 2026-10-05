# MistWANPerformance agent instructions

This file holds the rules that apply to MistWANPerformance only. The rules that apply to each
repository of this owner are in `AGENTS.md` at the repository root. Read `AGENTS.md` first. This
file adds to it, and it does not hold a copy of a rule from it. Where the two files disagree, obey
`AGENTS.md` for a writing rule, a safety rule, or a security rule.

## What this repository is

MistWANPerformance collects performance data for retail WAN circuits. The Python code reads
data from Juniper Mist Cloud and serves a Dash dashboard. It can write records to Snowflake. Redis
keeps data for the dashboard cache.

Network operations teams use the dashboard. Use Python 3.13 or newer. The package metadata lists
`Operating System :: OS Independent`. The container uses Debian Linux.

## Language and environment

Use Python 3.13. Use `uv` to sync the locked development environment.

```sh
uv sync --frozen --extra dev --python 3.13
```

If `uv` is not available, install the development requirements with `pip install -r
requirements-dev.txt`.

## Local gates

Run commands from the repository root. Use the virtual environment that `uv sync` creates.

| Gate | Command | Expected result |
| - | - | - |
| Compile | `python -m compileall -q src run_dashboard.py wsgi.py` | Exit code 0. |
| Lint | `ruff check .` | No findings. |
| Format | `black --check .` | No files need changes. |
| Types | `mypy .` | No type errors. |
| Tests | `python -m pytest -q` | All tests pass. |
| Dead code | `vulture src tests run_dashboard.py wsgi.py gunicorn_config.py --min-confidence 90` | No findings. |
| Security | `bandit -r src run_dashboard.py wsgi.py gunicorn_config.py -ll` | No high or critical findings. |
| Dependencies | `pip-audit -r requirements-dev.txt --no-deps --disable-pip` | No known vulnerable dependencies. |
| Offline documentation | `python -m pytest tests/test_offline_docs.py -q` | All documentation checks pass. |
| STE with dictionary | `ste-linter --config .ste-linter.toml --min-score 80 README.md TODO.md ProjectGoals.md AGENTS.md .github/copilot-instructions.md` | Every file scores 80 or higher. |
| STE without dictionary | `ste-linter --config .ste-linter.toml --min-score 80 --dictionary /nonexistent README.md TODO.md ProjectGoals.md AGENTS.md .github/copilot-instructions.md` | Every file scores 80 or higher. |
| Offline container | `podman build --target tests -t mistwan-tests . && podman run --rm --network none mistwan-tests` | The test image builds and all tests pass without network access. |

The tests block network connections. They run without credentials or a live Mist or Snowflake
account. The container test uses no published port.

## Architecture and conventions

`MistAPIClient` and `AsyncMistAPIClient` read data from Mist. Collectors in `src/collectors/`
normalize utilization, status, quality, and SLE data. `KPICalculator` and
`TimeAggregator` calculate measures and time summaries. `SnowflakeLoader` writes warehouse
records. Dashboard pages read from `DashboardDataProvider`, and Redis supports its cache.

Use the existing classes and data models. Find their current behavior in `src/` and their
operator details in `docs/operations.md`. Make sure each class or table name appears in `src/`.

Plan edits to `README.md`, `docs/changelog.md`, `Dockerfile`, `pyproject.toml`, and `uv.lock`.
These files contain project history, release data, or build rules.

## Safety in this repository

Git ignores `.env`. Keep credentials there. Keep logs, cache data, and exports in
`data/logs/`, `data/cache/`, and `data/exports/`.

Warning: `podman-compose down -v` can cause permanent loss of logs, exports, and cache data from
the two volumes. Do not run it until the user types `CONFIRM`.

`RedisCache.clear_all()` deletes keys with the cache prefix. The dashboard must fetch data again.
Do not call this method against a production cache until the user types
`CONFIRM`.

## Containers and ports

The Compose file defines the `dashboard` and `redis` services. It names their containers
`mistwan-dashboard` and `mistwan-redis`. The dashboard uses host port 8050, and Redis uses host port
6379. Build `mistwan-tests` from the `tests` target. Run it with `--network none` and `--rm`. Tests
do not use a port range. Do not publish a port for an offline test.

The Compose project name defaults to the repository directory because the file has no `name` key.
Name a temporary container for an issue or pull request `mistwan-<issue-or-pr>-<purpose>`. Run
`podman rm --force <name>` to remove a stopped test container.

Use `podman-compose down` to stop the local services and keep their volumes.

## Git and GitHub in this repository

Issue labels include `bug`, `documentation`, `enhancement`, and `ci`. Scope labels include
`docker` and `python:uv`. The repository has no pull request template, CodeQL workflow, or
`auto-merge` label.

The `CI` workflow runs on pull requests and pushes to `main`. A recent CI run took about six runner
minutes. `STE lint` checks pull requests and pushes to `main`. A recent run took about one runner
minute. `Stranded Branch Report` runs weekly and on request. A recent run took about one runner
minute.

For this repository, add one versioned JSON entry to `docs/changelog.md` for each code or
documentation change. Use the key format `version YY.MM.DD.HH.MM` and put the newest entry first.
This file holds MistWANPerformance change history. It is not an agent handoff file.

The release version uses `YY.MM.DD.HH.MM`. Keep `pyproject.toml`, `src/__init__.py`, `Dockerfile`,
and `uv.lock` in sync when a release changes. `tests/test_release_version.py` checks these values.
Keep the root README's six headings: What, How, Where, When, Why, and Who.

## Known pitfalls

- Issue #28 found that the asynchronous refresh worker could select the incorrect API mode. The
  repair selects a mode from the client type. Test sync and async clients.

- Mist device queries must request `type="gateway"` to return WAN gateways. The client does this
  in `src/api/mist_client.py`.

- Dash uses `app.run()`. Do not use the removed `app.run_server()` method. The dashboard disables
  the reloader in `src/dashboard/app.py`.

## Key files

| File | Purpose |
| - | - |
| `src/api/mist_client.py` | Mist API client. |
| `src/collectors/` | Mist metric collection. |
| `src/calculators/kpi_calculator.py` | KPI calculations. |
| `src/aggregators/time_aggregator.py` | Time summaries. |
| `src/loaders/snowflake_loader.py` | Snowflake writes. |
| `src/dashboard/` | Dashboard and data provider. |
| `src/utils/config.py` | Application configuration. |
| `tests/` | Offline tests and fixtures. |
| `docs/operations.md` | Setup, operations, and metric reference. |
| `docs/changelog.md` | Versioned product history. |
| `.env.example` | Names and sample values for configuration. |
| `docker-compose.yml` | Local dashboard and Redis services. |
| `pyproject.toml` and `uv.lock` | Package and locked dependency data. |

## External resources

- [Mist API documentation](https://api.mist.com/api/v1/docs)
- [mistapi Python package](https://github.com/tmunzer/mistapi_python)
- [Snowflake connector for Python](https://docs.snowflake.com/en/developer-guide/python-connector)
- [Redis documentation](https://redis.io/docs/latest/)
