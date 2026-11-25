# DeepEvidence 论文报告结果

| 原文对照 | Target identification · Fig. 2b | MoA and pathway reasoning · Fig. 3b | In vivo metabolic flux response · Fig. 3d |
| --- | ---: | ---: | ---: |
| DeepEvidence | 68% | 72% | 80% |
| Biomni | 56% | 44% | 68% |
| ToolUniverse | 40% | 44% | 52% |
| 通用 LLM（原文 general-purpose LLMs） | 42% | 52% | 60% |

数值来自正文 Results 的 “Drug discovery and preclinical research” 段落，图注定义柱图为均值及 95% CI。CSV 转录正文明确报告的点估计。论文在基准对比设置中报告使用 GPT-5 作为各 Agent 系统的共同基础模型，并描述了配有文献检索能力的 GPT-5 和 Sonnet-4.5 通用 LLM 对照。以上三项正文汇报通用 LLM 对照值时使用组名，因此这里保留该名称及汇报口径。[正文与 Fig. 2–3](https://pmc.ncbi.nlm.nih.gov/articles/PMC13449190/) · [正式论文](https://doi.org/10.1038/s42256-026-01266-0)

靶点题给定疾病与靶点目标，按候选项考查选择准确率。机制与通量题由领域专家整理单选或多选记录。Methods 将 gain 2 定义为完全符合文献和具体实验场景，gain 1 表示部分成立，gain 0 为干扰项。补充材料 A.1–A.4 展示各 Agent 和图记忆提示，补充表 1 列出工具，补充表 2–4 展示上述任务题例。项目主分数调用固定历史源码的官方判分，以发布数据中的 `answers` 为标签，单选比较唯一选项，多选比较完整集合。[补充材料入口](https://pmc.ncbi.nlm.nih.gov/articles/PMC13449190/#supplementary-materials) · [官方评分实现](https://github.com/RyanWangZf/BioDSA/blob/b12439eba3c77a9bab652015b17467c1f5bcf9ce/scripts/harbor_bdr_grade.py)

论文参考结果存于 [deepevidence_reported_results.csv](../results/published/deepevidence_reported_results.csv)。本项目使用当前统一模型，Direct LLM 仅使用题干和选项，Adapted 基线使用历史 DeepEvidence 的受限工具入口。项目实测分数见各运行目录中的 `tables.md`。两个结果来源有独立的表和运行口径。
