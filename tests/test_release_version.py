"""Prevent release metadata from drifting across distribution surfaces."""

import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

from packaging.version import Version

from src import __version__


class TestReleaseVersion:
    def test_distribution_versions_match(self):
        root = Path(__file__).resolve().parents[1]
        project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        labels = re.findall(
            r'^LABEL org\.opencontainers\.image\.version="([^"]+)"$',
            (root / "Dockerfile").read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
        assert project["version"] == __version__
        assert labels == [__version__]
        lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
        versions = [
            package["version"] for package in lock["package"] if package["name"] == project["name"]
        ]
        # Lock metadata uses PEP 440 normalization, which removes leading zeroes.
        assert versions == [str(Version(__version__))]

    def test_version_is_a_valid_minute_precision_calendar_timestamp(self):
        assert re.fullmatch(r"\d{2}(?:\.\d{2}){4}", __version__)
        timestamp = datetime.strptime(__version__, "%y.%m.%d.%H.%M").replace(tzinfo=UTC)
        assert timestamp.strftime("%y.%m.%d.%H.%M") == __version__
