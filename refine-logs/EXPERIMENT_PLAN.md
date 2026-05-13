# Experiment Plan: Verifiable Action Traces for Presentation Agents

**Version**: 1.0
**Date**: 2026-05-13
**Based on**: FINAL_PROPOSAL.md, REVIEW_SUMMARY.md

---

## Claims to Validate

| # | Claim | Experiment(s) |
|---|-------|---------------|
| C1 | AT+VR achieves 60%+ token reduction vs VLM reflection | E1: Token/Latency Benchmark |
| C2 | AT+VR achieves <5% quality gap vs VLM reflection | E2: Human Evaluation |
| C3 | Trace localization enables better repair than end-to-end | E3: Repair Task Comparison |
| C4 | Rules cover 70-80% of common slide failures | E4: Failure Taxonomy |

---

## Experiment Design

### E1: Token/Latency Benchmark

**Purpose**: Validate efficiency claims (C1)

**Setup**:
- 50 test tasks (10 each: topic→slides, paper→slides, doc→slides, business→slides, Chinese/English)
- 5 conditions (within-subject, counterbalanced):
  1. **Baseline**: No reflection
  2. **LLM-Reflect**: Text-only self-reflection
  3. **VLM-Reflect**: Image-based VLM reflection
  4. **AT+VR (Ours)**: Action trace + verifiable rules
  5. **Hybrid**: AT+VR + VLM fallback

**Metrics**:
- Token consumption (total, per slide)
- Latency (total, per reflection round)
- Rule coverage (% failures caught by rules)

**Decision Gate**:
- If AT+VR tokens < 50% of VLM-Reflect → C1 SUPPORTED
- If AT+VR tokens ≥ 50% → C1 WEAKLY SUPPORTED, need hybrid analysis

---

### E2: Human Evaluation

**Purpose**: Validate quality claims (C2)

**Setup**:
- Same 50 tasks as E1
- 3 evaluators per task (independent, blind to condition)
- Evaluators rate: Content Accuracy, Visual Quality, Coherence, Overall (1-5)

**Protocol**:
1. Show source document + generated slides
2. Elicic evaluate each dimension
3. Side-by-side for pairwise comparisons

**Decision Gate**:
- If AT+VR score ≥ 95% of VLM-Reflect → C2 SUPPORTED
- If AT+VR score ≥ 85% → C2 WEAKLY SUPPORTED
- If AT+VR score < 85% → C2 NOT SUPPORTED, need VLM fallback

---

### E3: Repair Task Comparison

**Purpose**: Validate trace localization advantage (C3)

**Setup**:
- 30 tasks with intentional perturbations (4 types × 30 = 120 local edits)
- 2 conditions:
  1. **End-to-End**: Re-generate entire slide
  2. **Trace-Local**: Repair only affected action

**Metrics**:
- Repair success rate (% of edits successfully fixed)
- Collateral damage (% of unrelated content changed)
- Token cost per repair

**Decision Gate**:
- If Trace-Local success rate ≥ End-to-End → C3 SUPPORTED
- If collateral damage lower → C3 STRONGLY SUPPORTED

---

### E4: Failure Taxonomy

**Purpose**: Establish rule coverage baseline (C4)

**Setup**:
- Collect all failures from E1-E3
- Categorize each failure:
  - Type: content / visual / structural / coherence
  - Hardness: hard (rule-detectable) / soft (subjective)
  - Fixability: localizable / global

**Metrics**:
- Rule coverage = (# hard failures caught by rules) / (# total hard failures)
- Soft failure rate = # soft failures / # total failures

**Decision Gate**:
- If rule coverage ≥ 70% → C4 SUPPORTED
- If rule coverage < 70% → need rule expansion

---

## Run Order

```
Week 1-2: Implementation
├── Implement action trace recorder
├── Implement verifiable rule engine (MVP rules)
└── Implement repair loop controller

Week 3: Pilot (E1-E4 small scale)
├── 20 tasks (pilot)
├── Debug pipeline
└── Freeze experiment protocol

Week 4: Main Experiments
├── E1: Token/Latency (50 tasks)
├── E2: Human Eval (50 tasks)
├── E3: Repair Task (30 tasks)
└── E4: Failure Taxonomy (analysis)

Week 5: Analysis & Write
├── Analyze results
├── Revise claims if needed
└── Write paper
```

---

## Budget

| Resource | Estimate | Notes |
|----------|----------|-------|
| GPU Hours | ~0 | No training; inference only |
| API Calls | ~500 | VLM reflection + rule engine + LLM generation |
| Human Eval | ~8 hours | 3 evaluators × 50 tasks × ~10 min |
| Total Cost | ~$50-100 | API calls only |

---

## Ablation Plan

| Ablation | Purpose | Included in |
|---------|---------|-------------|
| No reflection | Baseline | E1 |
| LLM-only reflection | Text reflection baseline | E1 |
| VLM-only reflection | Expensive baseline | E1, E2 |
| Rules only | Our core contribution | E1, E2 |
| Hybrid (rules + VLM fallback) | Full method | E1, E2 |
| Trace localization | Our unique contribution | E3 |
| End-to-end regeneration | Comparison | E3 |

---

## Decision Matrix

| C1 (Tokens) | C2 (Quality) | C4 (Coverage) | Action |
|-------------|-------------|--------------|--------|
| PASS | PASS | PASS | **Paper ready** |
| PASS | PASS | FAIL | Add more rules, re-test |
| PASS | FAIL | * | Add VLM fallback |
| FAIL | PASS | PASS | Re-frame as quality-first |
| FAIL | FAIL | * | RETHINK approach |

---

## Next Actions

1. [ ] Implement action trace recorder
2. [ ] Implement verifiable rule engine
3. [ ] Run 20-task pilot
4. [ ] Analyze pilot results
5. [ ] Run full experiments

---

**Verdict**: READY for implementation

