# FAO language review package for PyBehaviorLog 0.8.7

This document is a preparation pack for native review of the six supported FAO languages:
English, Arabic, Chinese (Simplified), Spanish, French, and Russian.

## Scope

The application already contains translation catalogs for the core user interface.
Version 0.8.7 adds new user-facing strings in the following areas:

- BORIS project import
- interactive timeline selection
- review notes workflow
- audit filters

## Required native-review pass

The following items still require a real human review by native speakers:

- scientific terminology consistency for behavioral coding
- reviewer-facing workflow language
- timeline interaction microcopy
- compact audit terminology
- import warnings for missing media files

## Review checklist

For each language, validate:

1. behavioral coding terminology is domain-appropriate
2. subject / individual / actor terms stay consistent
3. state / point event vocabulary is unambiguous
4. import/export wording is clear for scientific users
5. short action buttons remain concise enough for desktop and tablet screens
6. right-to-left layout remains readable in Arabic
7. Chinese labels remain compact and natural in Simplified Chinese

## Suggested reviewer process

1. Open the home page, a project detail page, analytics, and a session player page.
2. Switch through each supported language.
3. Trigger at least one import warning and one review workflow action.
4. Record wording issues directly in the corresponding `locale/*/LC_MESSAGES/django.po` file.
5. Recompile messages with `django-admin compilemessages` after each review batch.

## Important note

This document does not claim that native proofreading has already been completed.
It is a structured handoff to make that review efficient and reproducible.
