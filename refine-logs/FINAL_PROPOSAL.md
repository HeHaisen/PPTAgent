# Final Proposal: Verifiable Action Traces for Presentation Agents

**Version**: 1.0
**Date**: 2026-05-13
**Status**: READY (after Phase 1 refinement)
**Target Venue**: EMNLP Main

---

## Problem Anchor

Presentation generation agents currently fail in two orthogonal ways: (1) they cannot explain which action caused a quality failure, and (2) they rely on expensive VLM reflection to detect failures without principled rule-based grounding.

---

## Final Method Thesis

**We propose**: A structured action trace representation where each generation/edit action is explicitly recorded with pre/post state, enabling verifiable rule-based failure detection and trace-localized repair — without requiring expensive VLM calls or model fine-tuning.

### Core Insight

> For structured document generation (slides), visual quality failures are often **structurally determinable** (overflow, contrast, overlap) rather than **semantically subjective**. This means rules can catch 70-80% of failures at 10% of the cost of VLM reflection.

---

## Dominant Contribution

**Action Trace + Verifiable Reflection (AT+VR)**: A representation and verification framework for presentation agents that:
1. Records every generation/edit action as a structured trace entry
2. Applies deterministic rule-based verification to each trace entry
3. Localizes failures to specific trace actions for targeted repair
4. Uses VLM reflection only as fallback for "soft" failures rules cannot detect

---

## Key Claims (Must-Prove)

| # | Claim | Evidence Required |
|---|-------|------------------|
| 1 | AT+VR enables 60%+ token reduction vs VLM-only reflection | Ablation: VLM-only vs AT+VR token count |
| 2 | AT+VR achieves <5% quality gap vs VLM reflection | Human eval: side-by-side comparison |
| 3 | Trace localization enables better repair than end-to-end regeneration | Repair task: localized fix vs full regen |
| 4 | Rules cover 70-80% of common slide failures | Failure taxonomy: categorize 100+ failures |

---

## Method Architecture

```
User Request
    │
    ▼
┌─────────────────────────────────────┐
│     Action Trace Recorder           │
│  - create_slide → {action, state}   │
│  - write_slide → {action, state}    │
│  - generate_slide → {action, state}  │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│     Verifiable Rule Engine          │
│  Rules:                             │
│  - overflow detection (text/img)     │
│  - font size validation (≥12pt)     │
│  - WCAG contrast (≥4.5:1)           │
│  - element overlap detection        │
│  - layout repetition detection      │
│  - image distribution balance       │
│  Output: {violations[], action_id}  │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│     Repair Loop Controller          │
│  If violations:                     │
│    → localize to trace action       │
│    → propose targeted repair        │
│    → verify repair                  │
│    → iterate (max 3 rounds)         │
│  If "soft" failure (rules pass):    │
│    → fallback to LLM reflection    │
└─────────────────────────────────────┘
    │
    ▼
   Final PPTX
```

---

## What Complexity Was Rejected

| Rejected | Reason |
|----------|--------|
| Training-time reward optimization (AeSlides) | Requires fine-tuning, not generalizable |
| End-to-end VLM reflection | Too expensive, non-transparent |
| Complex rule conflict resolution | Over-engineering for MVP |
| Cross-slide coherence rules | Out of scope, future work |
| Generative rule learning | Out of scope, future work |

---

## Explicitly Optional Components

| Component | Status | When to Include |
|-----------|--------|-----------------|
| VLM fallback for soft failures | Optional | If human eval shows rule-only quality gap > 10% |
| Cross-action repair planning | Optional | If single-action repair success < 70% |
| Trace visualization for users | Optional | If user study shows debuggability matters |

---

## Rule Taxonomy (MVP)

### Hard Constraints (Rule-Verified)
- [x] Text overflow detection
- [x] Font size validation (title ≥24pt, body ≥14pt)
- [x] WCAG contrast ratio (text/bg ≥4.5:1)
- [x] Element overlap detection
- [x] Image boundary check
- [ ] Layout repetition detection (in progress)
- [ ] Image-text grounding (semantic alignment)

### Soft Constraints (LLM-Verified, Optional)
- Visual balance
- Color harmony
- Whitespace usage
- Typography hierarchy clarity

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Rules miss important failures | MEDIUM | Human eval + failure taxonomy; fallback to VLM |
| LLM repair introduces new failures | LOW | Verify repaired state with rules again |
| Trace overhead too high | LOW | Async logging; only record key actions |
| Generalization beyond slides | LOW | Framework is task-agnostic, rules are domain-specific |

---

## Next Steps After This Proposal

1. Implement action trace recorder
2. Extend rule engine with MVP rules
3. Run pilot: 50 tasks, compare 5 conditions
4. Analyze failure taxonomy
5. Human eval for quality comparison

---

## Related Work Positioning

| Paper | Our Delta |
|-------|-----------|
| PPTAgent | Add verifiable reflection + trace structure |
| AeSlides | Inference-time (no fine-tuning) + trace repair |
| Inverse Spec Rewards | No RL needed + explicit trace |
| PresentBench | We're generation method, not just benchmark |

---

**Verdict**: READY for experiment planning

