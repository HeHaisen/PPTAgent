# Research Idea Report

**Direction**: 基于当前 `~/projects/PPTAgentV3`，优化到可投稿 EMNLP/ACL 主会水平
**Generated**: 2026-05-13
**Updated**: 2026-05-13 (Phase 3-4-5 completed)
**Ideas evaluated**: 10 → 6 → 2 (merged)
**Pipeline Status**: COMPLETED

---

## Executive Summary

**Selected Idea**: Verifiable Action Traces for Presentation Agents (Merged Idea 2+4)

**Core Thesis**: Presentation agents should generate verifiable, editable action traces where each action is verified by structured rules and refined through an agentic reranking/repair loop — achieving comparable quality to VLM reflection at 60%+ lower token cost.

**Evidence**: Novelty check (7/10), Reviewer feedback (borderline, strengthened by merge), Method refinement complete, Experiment plan ready.

**Recommended Next Step**: Implement action trace recorder + verifiable rule engine, run pilot experiments.

---

## Literature Landscape

### Related Work

| Paper | Year | Relevance | Our Delta |
|-------|------|-----------|-----------|
| PPTAgent | 2025 | Edit-based generation | Add verifiable reflection + trace structure |
| AeSlides | 2026 | Verifiable rewards (training-time) | Inference-time, no fine-tuning |
| Inverse Spec Rewards | 2026 | RL for presentation | No RL + explicit trace |
| PresentBench | 2026 | Fine-grained evaluation | We're generation method |
| PPTBench | 2025 | Layout evaluation | We're generation method |
| ArcDeck | 2026 | Narrative-driven | Different focus (coherence vs efficiency) |

### Key Gap Identified

Existing work either:
1. Uses expensive VLM/LLM reflection without principled rule grounding
2. Uses training-time rewards requiring fine-tuning
3. Lacks explicit repair/trace structure for debuggability

**Our Position**: First work to combine inference-time verifiable rules + editable action traces for structured document generation.

---

## Phase 3: Novelty Check Results

**Score**: 7/10 — PROCEED ✅

**Closest Prior Work**:
- AeSlides (arXiv:2604.22840): Training-time GRPO with verifiable rewards
- Inverse Specification Rewards (arXiv:2603.16839): Training-time RL environment

**Key Differentiation**: Inference-time verification without model fine-tuning

**Risk**: Reviewer may cite AeSlides as prior art for rule-based approaches

---

## Phase 4: Reviewer Feedback

### Mock EMNLP Score (Idea 2 alone): 4/10 — Borderline Weak Reject

**Key Criticisms**:
1. Novelty Weak: "inference-time vs training-time is deployment choice"
2. Claims Unsupported: 60% reduction promises without data
3. Rule Completeness: Rules look like checklist
4. Evaluation Insufficient: Missing baselines and human eval

### Strengthening by Merge (Idea 2+4)

Merging Idea 2 (Verifiable Reflection) + Idea 4 (Action Traces) addresses:
- Stronger contribution: Two orthogonal innovations combined
- Better positioning: Controllable + Efficient framework
- Clearer differentiation from AeSlides (training vs inference, with vs without trace)

---

## Final Selected Idea: Verifiable Action Traces (Merged 2+4)

### Hypothesis

Presentation agents should generate verifiable, editable action traces (not end-to-end outputs), where each action can be verified by structured rules and refined through an agentic repair loop — combining controllability (trace-based editing) with efficiency (rule-based verification).

### Method Components

**1. Action Trace Representation**
```
{action_type, target_slide, parameters, pre_state, post_state, verification_status}
```

**2. Verifiable Reflection Layer**
- Hard constraints (rule-verified): overflow, font size, WCAG contrast, overlap, layout repetition, image-text grounding
- Soft constraints (LLM-verified, optional): visual balance, color harmony

**3. Repair Loop Architecture**
- Detect violations → localize to trace action → propose repair → verify → iterate (max 3 rounds)
- VLM fallback for soft failures

### Expected Outcomes

| Metric | Target |
|--------|--------|
| Token reduction vs VLM | 60%+ |
| Quality gap vs VLM | <5% |
| Rule coverage | 70-80% of failures |
| Repair success rate | >70% |

---

## Experiments (see refine-logs/EXPERIMENT_PLAN.md)

| Experiment | Purpose | Tasks | Key Metrics |
|------------|---------|-------|-------------|
| E1: Token/Latency | Efficiency | 50 | Tokens, latency |
| E2: Human Eval | Quality | 50 | Rating (1-5) |
| E3: Repair Task | Controllability | 30 | Success rate, collateral damage |
| E4: Failure Taxonomy | Rule coverage | Analysis | Rule coverage % |

**Budget**: ~$50-100 (API calls only), ~8 hours human eval

---

## Eliminated Ideas

| Idea | Reason |
|------|--------|
| Idea 1: SlideAgentBench | Benchmark paper, not method paper |
| Idea 3: Narrative-Visual Co-Planning | Too close to ArcDeck |
| Idea 5-6 | Secondary, merge candidates |

---

## Refined Proposal & Experiment Plan

- **Proposal**: `refine-logs/FINAL_PROPOSAL.md`
- **Review Summary**: `refine-logs/REVIEW_SUMMARY.md`
- **Experiment Plan**: `refine-logs/EXPERIMENT_PLAN.md`
- **Tracker**: `refine-logs/EXPERIMENT_TRACKER.md`
- **Pipeline Summary**: `refine-logs/PIPELINE_SUMMARY.md`

---

## Next Steps

- [ ] Implement action trace recorder
- [ ] Implement verifiable rule engine (MVP rules)
- [ ] Run 20-task pilot
- [ ] Run E1-E4 experiments
- [ ] Analyze results, refine claims
- [ ] Write paper

---

## Sources

- [PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides](https://arxiv.org/abs/2501.03936)
- [AeSlides: Incentivizing Aesthetic Layout in LLM-Based Slide Generation via Verifiable Rewards](https://arxiv.org/abs/2604.22840)
- [Learning to Present: Inverse Specification Rewards for Agentic Slide Generation](https://arxiv.org/abs/2603.16839)
- [PresentBench: A Fine-Grained Rubric-Based Benchmark for Slide Generation](https://arxiv.org/abs/2603.07244)
- [PPTBench: Towards Holistic Evaluation of Large Language Models for PowerPoint Layout and Design Understanding](https://arxiv.org/abs/2512.02624)
- [Narrative-Driven Paper-to-Slide Generation via ArcDeck](https://arxiv.org/abs/2604.11969)
- [PresentAgent-2: Towards Generalist Multimodal Presentation Agents](https://arxiv.org/abs/2605.11363)

---

**Pipeline Status**: ✅ COMPLETED

