# Pipeline Summary

**Problem**: Presentation agents fail in two orthogonal ways: (1) cannot explain which action caused a quality failure, and (2) rely on expensive VLM reflection without principled rule-based grounding.

**Final Method Thesis**: Action Trace + Verifiable Reflection (AT+VR) — a representation and verification framework that records every generation/edit action as structured trace entries, applies deterministic rule-based verification, localizes failures to specific actions, and uses VLM reflection only as fallback.

**Final Verdict**: **READY** (for experiment implementation)

**Date**: 2026-05-13

---

## Final Deliverables

| File | Description |
|------|-------------|
| `refine-logs/FINAL_PROPOSAL.md` | Full method proposal with claims |
| `refine-logs/REVIEW_SUMMARY.md` | Reviewer feedback and transformations |
| `refine-logs/EXPERIMENT_PLAN.md` | Claim-driven experiment roadmap |
| `refine-logs/EXPERIMENT_TRACKER.md` | Experiment execution tracker |
| `idea-stage/IDEA_REPORT.md` | Original idea landscape |

---

## Contribution Snapshot

**Dominant Contribution**: Action Trace + Verifiable Reflection framework combining controllability (trace-based repair) with efficiency (rule-based verification)

**Optional Supporting Contribution**: Hybrid mode with VLM fallback for soft failures

**Explicitly Rejected Complexity**:
- Training-time reward optimization (AeSlides approach)
- Complex rule conflict resolution
- Cross-slide coherence rules
- Generative rule learning

---

## Must-Prove Claims

1. **C1**: AT+VR achieves 60%+ token reduction vs VLM reflection
2. **C2**: AT+VR achieves <5% quality gap vs VLM reflection
3. **C3**: Trace localization enables better repair than end-to-end regeneration
4. **C4**: Rules cover 70-80% of common slide failures

---

## First Runs to Launch

1. **Implement action trace recorder** — Standardize MCP tool calls into trace entries
2. **Implement verifiable rule engine** — MVP: overflow, font size, WCAG contrast, overlap
3. **Run 20-task pilot** — Validate pipeline, freeze experiment protocol
4. **Run E1: Token/Latency Benchmark** — 50 tasks, 5 conditions

---

## Main Risks

| Risk | Mitigation |
|------|------------|
| Rules miss important failures | Human eval + VLM fallback |
| Quality gap too large | If >10%, add VLM fallback |
| Trace overhead high | Async logging, key actions only |

---

## Novelty Positioning

| Prior Work | Our Delta |
|------------|-----------|
| PPTAgent | Add verifiable reflection + trace structure |
| AeSlides | Inference-time (no fine-tuning) + trace repair |
| Inverse Spec Rewards | No RL needed + explicit trace |
| PresentBench/PPTBench | We're generation method, not just benchmark |

---

## Next Action

- **Proceed to `/run-experiment`** — Implement action trace recorder and verifiable rule engine, then run pilot

---

## Pipeline History

| Phase | Status | Output |
|-------|--------|--------|
| Phase 0: Research Brief | ✅ | No brief found, used IDEA_REPORT.md |
| Phase 1: Literature Survey | ✅ | IDEA_REPORT.md (existing) |
| Phase 2: Idea Generation | ✅ | 6 ideas, selected Idea 2 |
| Phase 3: Novelty Check | ✅ | 7/10, PROCEED with refinement |
| Phase 4: Review | ✅ | 4/10 (weak), strengthened by merging Idea 2+4 |
| Phase 4.5: Method Refinement | ✅ | FINAL_PROPOSAL.md, REVIEW_SUMMARY.md |
| Phase 5: Experiment Plan | ✅ | EXPERIMENT_PLAN.md, EXPERIMENT_TRACKER.md |

---

**Ready for implementation**.

