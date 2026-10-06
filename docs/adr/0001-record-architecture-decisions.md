# ADR-0001: Record architecture decisions

- Status: accepted
- Date: 2026-10-06

## Context

The project combines photogrammetry, geodata, routing, a web app and an AI
assistant. Many choices depend on verified constraints (Apple Silicon only, no
model training, free-tier limits, copyrighted input data) that are easy to forget.

## Decision

Significant decisions are recorded as short ADRs in `docs/adr/NNNN-title.md`
(context, decision, consequences). The full design lives in
[`docs/superpowers/specs/2026-10-06-campus-map-design.md`](../superpowers/specs/2026-10-06-campus-map-design.md).

## Consequences

Decisions are reviewable in pull requests, and later phases (indoor navigation,
deployment) can revisit them explicitly instead of silently.
