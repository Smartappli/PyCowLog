# Changelog

## 0.9.3

- Refined review queue filtering logic into a shared helper for maintainability.
- Aligned review-segment CSV export with active queue filters used in the UI.
- Bumped release metadata and docs to 0.9.3.
- Documented Granian as the default ASGI command for local startup parity.

## 0.9.2

- Added batch assignment for review segments directly from the session player.
- Added finer review queue filters (project, status, assignee, reviewer, and text search).
- Added CSV analytics export for review segments from the review queue.

## 0.9.1

- Added segment-level review queues and session review segments.
- Added review queue dashboard and session-level segment CRUD screens.
- Included review segments in 0.9.1 session exports/imports and project cloning.

## 0.9

- Added import-as-new-project workflow from BORIS project JSON or PyBehaviorLog bundle ZIP/JSON.
- Added project cloning with optional session and video metadata duplication.
- Added `/health/` and `/release.json` operational endpoints.
- Added management commands for release metadata and project bundle export.
- Added Docker health checks for the ASGI service.

## 0.8.9

- Added server-side undo/redo for event operations.
- Expanded BORIS-like tabular imports and picture sequence handling.
