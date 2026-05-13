# Research Idea Report

**Direction**: 基于当前 `~/projects/PPTAgentV3`，优化到可投稿 EMNLP/ACL 主会水平  
**Generated**: 2026-05-13  
**Ideas evaluated**: 10 generated → 6 survived filtering → 0 piloted → 4 recommended  
**Pilot status**: skipped; 当前阶段是研究选题规划，尚未请求启动实验。

## Landscape Summary

当前 PPTAgentV3 已经不只是原始 PPTAgent 的复现，而是一个 Research → Design/PPTAgent 的多智能体生成系统。代码层面已有两条生成路径：模板驱动的 PPTAgent 路径，以及 HTML/CSS 自由设计路径；并且加入了 MCP 工具链、实时预览、增量生成、取消机制、可读性检查、WCAG 对比度检查、图片分布检查、会话恢复和并发生成等工程能力。

相关研究从 2025 年 PPTAgent 开始，把“文档到演示文稿”从 text-to-slides 提升到内容、视觉、结构三维联合生成与评估。2026 年的趋势很明显：PresentBench/PPTBench 强调更细粒度的评测，ArcDeck 强调论文到 slides 的叙事结构，AeSlides/Inverse Specification Rewards 强调可验证奖励或 RL 优化视觉布局，PresentAgent-2 则扩展到多模态 presentation agents。

因此，如果目标是 EMNLP 级别，最危险的方向是“继续堆工程功能”或“比 PPTAgent 多几个工具”。更有机会的方向是：把当前系统中的工程机制抽象成一个可评估、可复现、可泛化的研究问题，例如“反思式演示文稿智能体如何被可验证信号训练/选择/评估”、“演示文稿生成中的叙事-视觉双约束如何统一”、“从用户意图到 slides 的可控编辑轨迹如何建模”。

## Recommended Ideas (ranked)

### Idea 1: SlideAgentBench-CN/EN — 面向真实演示文稿智能体的过程级评测基准

- **Hypothesis**: 现有评测多关注最终 slides，而真实系统失败往往发生在 research、outline、layout selection、editing、visual inspection 等中间步骤；过程级评测能更稳定地区分 agent 能力，并指导系统改进。
- **Minimum experiment**: 收集 80-150 个任务，覆盖 topic-to-slides、paper-to-slides、doc-to-slides、business-report-to-slides；为每个任务保存 manuscript、outline、layout choice、tool calls、final PPTX/PDF，并设计 step-level rubric。
- **Expected outcome**: 若 benchmark 能揭示不同模型/agent 配置在中间步骤的显著差异，即使最终质量差异不大，也构成贡献。
- **Novelty**: 8/10 — closest work: PresentBench/PPTBench/PPTEval；差异是过程级 agent trace、工具调用、中文/英文真实任务和可干预诊断。
- **Feasibility**: 高；主要是数据构建、日志标准化、评测脚本和人工/LLM rubric 标注；无需大规模 GPU。
- **Risk**: LOW-MEDIUM
- **Contribution type**: benchmark + diagnostic evaluation
- **Pilot result**: SKIPPED — 可先用现有 `runs/` 和 20 个新任务做小规模可行性验证。
- **Reviewer's likely objection**: “只是又一个 benchmark，和 PresentBench/PPTBench 不够不同。”
- **Why we should do this**: 当前 PPTAgentV3 已天然记录 agent 历史和中间产物，做过程级评测的边际成本低；EMNLP/ACL 对 agent evaluation 和 multilingual evaluation 都较友好。

### Idea 2: Verifiable Reflection for Slide Generation — 用可验证视觉/结构约束替代昂贵多模态反思

- **Hypothesis**: 许多 slide 质量问题可以由可验证规则捕获，例如溢出、字号、对比度、元素重叠、图文错配、布局重复、图片分布不均；把这些信号纳入 search/rerank/retry loop，可以以更低成本接近或超过 heavy multimodal reflection。
- **Minimum experiment**: 在当前 `inspect_slide` 的字号/对比度基础上加入 overlap、safe margin、density、alignment、image-text grounding、layout diversity 等规则；比较 no-reflection、LLM self-reflection、VLM reflection、verifiable-reflection、hybrid-reflection。
- **Expected outcome**: 成功指标是质量提升接近 VLM reflection，但 token/cost/latency 更低；失败也可分析哪些美学问题不可被规则捕获。
- **Novelty**: 7/10 — closest work: AeSlides 使用 verifiable rewards，Inverse Specification Rewards 用 RL 环境；差异是 inference-time agentic reflection/reranking，而不是只做训练奖励。
- **Feasibility**: 高；已有 `inspect_slide`、HTML rendering、PPTX conversion 和 warnings 机制。
- **Risk**: MEDIUM
- **Contribution type**: method + efficiency/quality evaluation
- **Pilot result**: SKIPPED — 可用 30 个固定 prompts 做 A/B 测试，人工或 LLM judge 评估。
- **Reviewer's likely objection**: “规则过于工程化，不够 NLP。”
- **Why we should do this**: 需要把贡献表述为“可验证反馈如何降低多模态 agent 反思成本”，而不是“加了一堆检查器”。这与当前代码最近新增的 WCAG、布局多样性和图片检查高度匹配。

### Idea 3: Narrative-Visual Co-Planning — 面向长文档/论文的叙事弧线与视觉布局联合规划

- **Hypothesis**: 文档到 slides 的核心不是摘要，而是把 source document 的 discourse structure 映射为 audience-facing narrative arc，同时每个 narrative role 对应不同视觉布局策略。
- **Minimum experiment**: 在 Research Agent 输出 manuscript 后，显式构建 narrative state：hook、problem、evidence、method、result、takeaway、transition；layout selector 不只看 slide content，还看 narrative role、前后页节奏和视觉负载。
- **Expected outcome**: 若叙事角色约束提升 coherence、transition quality、audience comprehension，则可形成方法贡献。
- **Novelty**: 7/10 — closest work: ArcDeck 强调 discourse tree 和 paper-to-slide narrative；差异是把 narrative role 与 visual layout/control 联合建模，并支持多来源 research-to-slide。
- **Feasibility**: 中高；需要改 outline schema、layout selector 输入、评测 coherence rubric。
- **Risk**: MEDIUM
- **Contribution type**: method + analysis
- **Pilot result**: SKIPPED — 可先只在 paper-to-slide 和 report-to-slide 两类任务上做 20-30 个样本。
- **Reviewer's likely objection**: “和 ArcDeck 太近。”
- **Why we should do this**: 必须强调 PPTAgentV3 的优势：不是单篇 paper-to-slide，而是 research agent 汇聚多来源材料后进行 narrative-visual co-planning。

### Idea 4: Editable Slide Generation as Action Traces — 从端到端生成转向可解释、可修复的编辑轨迹

- **Hypothesis**: 对用户真正有用的 slides generator 应输出可修复的 edit trace，而不是一次性图片或 HTML；显式编辑轨迹能提升可控性、debuggability 和 human-in-the-loop 修复效率。
- **Minimum experiment**: 标准化当前 PPTAgent 的 create/write/generate slide tool calls，构造 edit-trace representation；评测相同最终质量下，trace 是否更容易被模型或人类修复局部错误。
- **Expected outcome**: 在局部修改任务中，edit-trace 方法比直接重生成更稳定、更少破坏无关内容。
- **Novelty**: 8/10 — closest work: PPTAgent edit-based generation；差异是把 action trace 作为研究对象，加入 repair benchmark 和可控编辑评估。
- **Feasibility**: 中；已有 MCP 工具调用与 command history，但需要设计局部编辑任务和指标。
- **Risk**: MEDIUM-HIGH
- **Contribution type**: representation + benchmark + method
- **Pilot result**: SKIPPED — 可从 20 个生成失败案例构造局部修复集。
- **Reviewer's likely objection**: “这是系统论文，不是 EMNLP。”
- **Why we should do this**: 如果结合 natural-language edit instruction、agent tool-use planning、可解释 edit trajectories，就能落在 NLP/agent 范围内。

## Secondary Ideas

### Idea 5: Multilingual Presentation Generation Stress Test

- **Summary**: 系统性研究中英跨语言 slides 生成中的 length expansion、layout overflow、terminology consistency 和 audience adaptation。
- **Why lower ranked**: 可行且贴近当前代码的 `length_factor`，但贡献可能偏窄；适合作为 Idea 1 benchmark 的一个子集或分析章节。

### Idea 6: Image Asset Grounding for Presentation Agents

- **Summary**: 评估和改进 slide generation 中图片选择、图片类型匹配、caption grounding 和跨页图片分布。
- **Why lower ranked**: 与当前 recent commits 高度贴合，但单独成文风险是“视觉素材工程”；建议并入 Idea 2 或 Idea 1。

## Eliminated Ideas (for reference)

| Idea | Reason eliminated |
|------|-------------------|
| 端到端训练一个专用 slide LLM | 需要大量高质量 PPTX/HTML 数据和 GPU，超出短期可行范围 |
| 只做更漂亮的模板或主题库 | 工程价值高，但研究贡献弱 |
| 只把 PPTAgentV3 包装成 autonomous presentation video agent | PresentAgent-2 已覆盖 presentation video/generalist agent 方向，追赶风险高 |
| 单纯复现 AeSlides 的 RL reward | 近期相近工作太强，除非提出 inference-time verifiable reflection 或新 reward family |
| 只优化 WebUI/preview/cache | 产品体验重要，但不构成 EMNLP 主贡献 |
| 只做中文 PPT 生成 | 可作为数据维度，但单独 novelty 不够 |

## Suggested Execution Order

1. **先做 Idea 1 的小型 benchmark pilot**：20 个任务 × 3 个系统配置，验证过程级指标是否能区分失败模式。
2. **同步实现 Idea 2 的 verifiable reflection 扩展**：overlap、density、alignment、image grounding、layout repetition，形成可干预方法。
3. **把 Idea 1 + Idea 2 合并为主线 paper**：标题可类似 *Process-Supervised Evaluation and Verifiable Reflection for Presentation Agents*。
4. **若 coherence 仍是主要短板，再加入 Idea 3**：作为 narrative planning module 和 ablation。
5. **把 Idea 4 作为 repair benchmark/analysis**：如果时间足够，可成为第二篇或附加章节。

## Concrete EMNLP Paper Shape

### Recommended paper thesis

> Presentation generation agents should not be evaluated or improved only at the final-slide level. By exposing intermediate process traces and using verifiable visual/structural feedback, we can diagnose, repair, and improve multimodal slide generation more reliably and cheaply.

### Possible title

- *Beyond Final Slides: Process-Supervised Evaluation and Verifiable Reflection for Presentation Agents*
- *Diagnosing and Repairing Presentation Agents with Process Traces and Verifiable Visual Feedback*
- *SlideAgentBench: Fine-Grained Process Evaluation for Multimodal Presentation Generation Agents*

### Core experiments

1. **Benchmark validity**: process metrics correlate with human judgments better than final-only coarse scores.
2. **Ablation**: no reflection vs text self-reflection vs VLM reflection vs verifiable reflection vs hybrid.
3. **Failure taxonomy**: content omission, narrative discontinuity, layout mismatch, visual overflow, unreadable text, image misuse.
4. **Cost-quality tradeoff**: verifiable reflection recovers most quality gains at lower token/call cost.
5. **Generalization**: topic-to-slide, document-to-slide, paper-to-slide, Chinese/English tasks.

## Next Steps

- [ ] Define 20-task pilot set and freeze prompts/templates.
- [ ] Add structured trace export for Research → Outline → Layout → Edit → Inspect.
- [ ] Extend `inspect_slide` into a richer verifiable audit module.
- [ ] Run 3-system pilot: current PPTAgentV3, no-reflection baseline, verifiable-reflection variant.
- [ ] Use `/result-to-claim` after pilot to decide whether to scale.

## Sources

- [PPTAgent: Generating and Evaluating Presentations Beyond Text-to-Slides](https://arxiv.org/abs/2501.03936)
- [PresentBench: A Fine-Grained Rubric-Based Benchmark for Slide Generation](https://arxiv.org/abs/2603.07244)
- [PPTBench: Towards Holistic Evaluation of Large Language Models for PowerPoint Layout and Design Understanding](https://arxiv.org/abs/2512.02624)
- [Learning to Present: Inverse Specification Rewards for Agentic Slide Generation](https://arxiv.org/abs/2603.16839)
- [AeSlides: Incentivizing Aesthetic Layout in LLM-Based Slide Generation via Verifiable Rewards](https://arxiv.org/abs/2604.22840)
- [Narrative-Driven Paper-to-Slide Generation via ArcDeck](https://arxiv.org/abs/2604.11969)
- [PresentAgent-2: Towards Generalist Multimodal Presentation Agents](https://arxiv.org/abs/2605.11363)
