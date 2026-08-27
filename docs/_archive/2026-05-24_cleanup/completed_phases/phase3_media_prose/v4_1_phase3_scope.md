# Phase 3 — Scope

**Date:** 2026-05-14

## Purpose

Evaluate `gemma4:e4b` as a dedicated small model for media/prose/content workflows, keeping qwen3:14b focused on trading intelligence and gemma3-overnight on deep reasoning.

## Why Separate from Phase 2

Phase 2 was about embedding/RAG quality. Phase 3 is about inference model selection for non-trading content tasks. Different concern, different model, different risk profile.

## Candidate Model

`gemma4:e4b` — ~3-4 GB Q4, can coexist with qwen3:14b (10 GB) on 16 GB VRAM.

## Approved Workflows

- YouTube transcript summarization
- Long transcript cleanup
- Content digest drafting
- Report narrative polish
- Article summarization
- Media metadata enrichment
- Post-market narrative drafting (read-only)
- Weekly summary prose drafting (read-only)
- Non-trading content classification

## Blocked Workflows

- Broker/execution/risk gates
- Order placement
- Active stop/target execution
- Market-hours trading decisions
- Telegram/OpenClaw interactive trading

## Safety

- Read-only content workflows only
- No trade recommendations from Phase 3 model
- Fallback to qwen3:14b
- No .env changes
- No broker/holdings/execution changes
