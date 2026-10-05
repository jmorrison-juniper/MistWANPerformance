"""Guard the CodeQL workflow and the misthelper-devtools pins against drift.

A future edit can remove a trigger, widen a permission, cancel a run on main,
or leave a reusable workflow on an old release. Each test reads the workflow
files and fails when one of these values changes.
"""

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]  # The repository root holds .github.
WORKFLOWS = ROOT / ".github" / "workflows"  # The directory that GitHub Actions reads.
DEVTOOLS_COMMIT = "da02d4c6a2163d1882f2ad25fce80b8ba38304d1"  # The v0.6.2 release commit.
DEVTOOLS_USES = re.compile(  # Each reusable workflow call to misthelper-devtools.
    r"uses:\s*jmorrison-juniper/misthelper-devtools/\S+@(\S+)(.*)$", re.MULTILINE
)


class TestWorkflowContracts:
    """Check the values of the workflow files that a review must not lose."""

    @staticmethod
    def load_workflow(name: str) -> dict[Any, Any]:
        """Read one workflow file and return its parsed mapping."""
        document = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))  # Parse the file.
        assert isinstance(document, dict), name  # A workflow is always a mapping.
        return document  # Give the parsed workflow to the test.

    def test_every_devtools_pin_names_release_0_6_2(self) -> None:
        """Each misthelper-devtools call pins the v0.6.2 commit with its comment."""
        pins = [  # Collect each pin from each workflow file.
            match
            for path in sorted(WORKFLOWS.glob("*.yml"))
            for match in DEVTOOLS_USES.findall(path.read_text(encoding="utf-8"))
        ]
        assert len(pins) >= 5, pins  # CI, STE lint, the branch report, and CodeQL call devtools.
        for commit, comment in pins:  # Examine each pin and its release comment.
            assert commit == DEVTOOLS_COMMIT, commit  # An old commit is drift.
            assert comment.strip() == "# v0.6.2", comment  # Dependabot reads the comment.

    def test_codeql_runs_on_each_required_event(self) -> None:
        """CodeQL runs on pull requests, pushes to main, a schedule, and request."""
        workflow = self.load_workflow("codeql.yml")  # Read the CodeQL caller.
        events = workflow[True]  # PyYAML reads the bare key "on" as the boolean True.
        assert set(events) == {"pull_request", "push", "schedule", "workflow_dispatch"}
        assert events["pull_request"] is None  # No branch filter, so a stacked PR gets a scan.
        assert events["push"] == {"branches": ["main"]}  # One event starts one run.

    def test_codeql_permissions_are_minimal(self) -> None:
        """The workflow grants no scope at the top and three scopes to the job."""
        workflow = self.load_workflow("codeql.yml")  # Read the CodeQL caller.
        assert workflow["permissions"] == {}  # The empty map removes every default scope.
        job = workflow["jobs"]["codeql"]  # Code scanning keys alerts on this job ID.
        assert job["permissions"] == {
            "actions": "read",
            "contents": "read",
            "security-events": "write",
        }
        assert job["with"] == {  # The inputs that select the language and the configuration.
            "languages": '["python"]',
            "config-file": "./.github/codeql/codeql-config.yml",
        }
        assert (ROOT / ".github" / "codeql" / "codeql-config.yml").is_file()  # The input exists.

    def test_codeql_never_cancels_a_main_run(self) -> None:
        """A new commit cancels an older pull request run but never a main run."""
        concurrency = self.load_workflow("codeql.yml")["concurrency"]  # Read the group settings.
        assert "github.head_ref || github.ref" in concurrency["group"]  # One group per branch.
        assert concurrency["cancel-in-progress"] == "${{ github.ref != 'refs/heads/main' }}"
