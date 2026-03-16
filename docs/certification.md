# Compatibility certification notes for PyBehaviorLog 0.9.1

PyBehaviorLog 0.9.1 introduces a small built-in compatibility corpus and round-trip comparison helpers.

## Included fixture families

The repository ships reference fixtures under `tracker/tests/fixtures/` for:

- BORIS observation JSON
- BORIS project JSON
- CowLog-compatible plain-text results

These fixtures are intentionally compact. They are meant to verify the documented interchange paths that PyBehaviorLog actively supports, not every historical file shape ever produced by third-party tools.

## Round-trip strategy

The 0.9 test suite validates compatibility with this workflow:

1. Import a BORIS or CowLog fixture.
2. Persist the imported content in the Django data model.
3. Export the session or project back to a PyBehaviorLog/BORIS-compatible payload.
4. Normalize the source and exported payloads.
5. Compare event rows, annotations, variables, and project entities programmatically.

## Why normalization is necessary

BORIS, CowLog, and PyBehaviorLog do not expose exactly the same schemas. The round-trip comparison layer therefore normalizes:

- event time precision
- behavior names
- event kinds (`point`, `start`, `stop`)
- modifier sets
- subject sets
- annotation text
- independent-variable mappings

This allows CI to focus on semantic equivalence instead of raw JSON shape differences.

## Current scope

0.9 improves confidence, but it is still not a blanket claim of universal compatibility with every historical BORIS or CowLog artifact.

What it does provide is a **repeatable, testable certification baseline** for the documented exchange families that the project already supports.

## Next expansion path

A future certification pass can extend the fixture corpus with:

- BORIS live-observation payloads
- BORIS picture-observation payloads
- multi-subject state-heavy projects
- legacy or edge-case CowLog exports
- gold files captured from real-world operator datasets


## Additional notes for 0.9

Version 0.9 extends the compatibility and review toolchain with server-side undo/redo for event operations, broader BORIS-style spreadsheet imports, and richer handling of picture-based media paths and image sequences.


## Operational additions in 0.9

Version 0.9 adds a project lifecycle layer on top of the existing compatibility tooling:

- project import as a **new project** from BORIS project JSON or PyBehaviorLog bundles
- project cloning for parallel review, training, or branching workflows
- deployment-oriented `/health/` and `/release.json` endpoints
- management commands for bundle export and release reporting
