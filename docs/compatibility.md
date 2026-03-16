# Compatibility profile for PyBehaviorLog 0.8.9

PyBehaviorLog 0.8.9 strengthens interoperability with BORIS and CowLog around the formats and workflows that are publicly documented.

## BORIS coverage

### Implemented in 0.8.9

- BORIS-compatible observation JSON export
- BORIS-compatible project JSON export
- Project import from BORIS-like project JSON payloads using both list and mapping shapes
- Observation import from BORIS-like observation JSON payloads
- Behavioral sequence export
- Praat TextGrid export
- Binary table export
- CSV, TSV, JSON, XLSX tabular exports
- Transition summaries and interval analytics inside PyBehaviorLog exports

### Current positioning

This is a **strong compatibility layer**, but not a formal certification against every historical BORIS project file ever produced.

The safest paths are:

- BORIS JSON project/observation workflows documented in the BORIS user guide
- BORIS-style tabular exports
- Structured round-trips through PyBehaviorLog reproducibility bundles

## CowLog coverage

### Implemented in 0.8.9

- Import of documented CowLog-like plain-text coding result files
- Export of CowLog-compatible plain-text result files
- Mapping through behavior names and keyboard shortcuts
- Modifier-aware import/export for plain-text rows

### Current positioning

CowLog compatibility in 0.8.9 focuses on the **documented plain-text coding result workflow**.

CowLog plain-text exports do not preserve all PyBehaviorLog/BORIS semantics with the same fidelity, especially for:

- paired state events
- annotations
- richer review/audit metadata
- observation variables

For those cases, BORIS JSON and PyBehaviorLog JSON remain the preferred interchange formats.


## Built-in certification baseline

Version 0.8.9 adds a compact fixture corpus and automated round-trip tests for:

- BORIS observation JSON
- BORIS project JSON
- CowLog-compatible plain-text result files

Those fixtures are executed in the Django test suite and compared through normalization helpers so CI can detect semantic regressions even when raw JSON shapes differ.

## Compatibility reports

PyBehaviorLog 0.8.9 adds machine-readable compatibility reports at both project and session level.

They summarize:

- detected or targeted exchange family
- documented import/export families
- readiness warnings
- feature mismatches that may reduce fidelity

## Recommended certification workflow

If you want to move toward a stronger "certified compatibility" claim, use this workflow:

1. Build a gold corpus of BORIS and CowLog reference files.
2. Import them into PyBehaviorLog.
3. Export them back out.
4. Re-import the exported files.
5. Compare events, subjects, modifiers, variables, and timing programmatically.
6. Store the round-trip reports in CI.

That approach is the right path toward a future compatibility certification release.


### Added in 0.8.9

- BORIS-style tabular session imports from CSV, TSV, and XLSX files
- relative media paths included in project/session JSON payloads and reproducibility bundles
- lightweight media diagnostics for compatible local audio files, including waveform previews and a coarse spectrogram
- additional HTML and SQL exports for review and downstream analysis pipelines


## Additional notes for 0.8.9

Version 0.8.9 extends the compatibility and review toolchain with server-side undo/redo for event operations, broader BORIS-style spreadsheet imports, and richer handling of picture-based media paths and image sequences.
