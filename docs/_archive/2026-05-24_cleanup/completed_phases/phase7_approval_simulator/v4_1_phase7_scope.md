# Phase 7 Scope — Approval Simulator

**Date:** 2026-05-16

Phase 7 is read-only decision support. It does not approve proposals, create paper trades, submit orders, mutate proposal state, or bypass Phase 6 gates.

## Simulator Flow
Load → Freshness → Session → Revalidation → Risk Gate → Order Preview → Return

## Forbidden
- Trade creation, order submission, proposal mutation, gate bypass, override buttons
