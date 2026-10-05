# Changelog

Historical entries are preserved in [the operations reference](operations.md#changelog).
The root README links here so its six-question introduction remains concise.

```json
{
  "version 26.10.05.17.25": {
    "security": [
      "Add CodeQL analysis for Python through the misthelper-devtools v0.6.2 reusable workflow; a run on main is never cancelled"
    ],
    "compatibility": [
      "Move every misthelper-devtools workflow pin to v0.6.2 (da02d4c6)"
    ],
    "testing/validation": [
      "Check the devtools pins and the CodeQL triggers, permissions, inputs, and concurrency in a workflow contract test"
    ],
    "documentation": [
      "List each workflow, its events, and its check names in the repository instructions"
    ]
  },
  "version 26.10.05.05.06": {
    "documentation": [
      "Adopt the canonical generic AGENTS.md and the repository-specific Copilot instructions"
    ],
    "testing/validation": [
      "Check the two-file instruction layout and grade both files with and without the STE dictionary"
    ]
  },
  "version 26.10.05.02.10": {
    "compatibility": [
      "Align package, runtime, container, and lock metadata with the UTC release version; keep dependency versions unchanged"
    ],
    "testing/validation": [
      "Check release version consistency and calendar format in local and offline container tests"
    ]
  },
  "version 26.10.04.20.31": {
    "bug-fixes": [
      "Select async refresh API mode from the actual client type and report that mode accurately"
    ],
    "testing/validation": [
      "Cover both client types and legacy flags, empty responses, rate limits, caching, and callbacks",
      "Include documentation and captured screenshots in the offline container test stage"
    ],
    "documentation": [
      "Limit root README to six questions; preserve detailed guidance under docs and add genuine offline dashboard captures"
    ]
  }
}
```
