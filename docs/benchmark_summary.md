# BioMDT Phase 3 Benchmark

## Problem

评价模型能否在靶点识别、药物机制判断和体内代谢通量预测中整合异构生物医学证据，并追溯关键结论到适用条件下的原始研究。选择题成绩、证据核验和运行成本各自回答不同的研究问题。

## Data

输入沿用 DeepEvidence 发布的三个子任务，每个任务 25 题。推理程序只获得单题的 ID、任务、原始题干和候选项。统一运行器在推理结束后读取独立参考文件并调用作者评分脚本。官方协议分母为 75 题，未暴露协议排除三个开发案例，分母为 72 题。六条 `answers` 与 `gains` 差异保存在原数据异常记录中，评分使用官方 `answers`。[Data 说明](data_summary.md)

## Model

| 方法 | 运行口径 |
| --- | --- |
| Direct LLM | 接收题干及原始候选项，外部工具调用为零 |
| DeepEvidence (Adapted) | 历史 BioDSA 提交 `b12439eba3c77a9bab652015b17467c1f5bcf9ce`，原 Orchestrator、BFRS、DFRS、检索、全文、记忆图和最终综合，开放 `pubmed_papers` 组内工具，禁用模型自选的代码执行工具 |
| BioMDT | 原六角色方法，命题证据图、缺口调度、上下文融合及决策，默认开放 UniProt、Open Targets、KEGG、Reactome、ChEMBL、PubMed、PubTator |

DeepEvidence 保留两种内部预算档位。作者配置对应主搜索轮、主动作、子动作预算 5/20/5。项目配置为 1/5/3，Smoke 使用该配置，运行日志记录实际动作。两档在本入口均使用受限工具范围，因此均以 Adapted 报告。默认 `native` 方案衡量两套实际系统配置。配置 `shared-literature` 时将 BioMDT 的外部查询也收窄到 PubMed、PubTator，两者仍保留各自的检索接口和调度算法。该范围选项未用于 Smoke。统一的模型、工具和 Token 调用上限用于控制资源，方法内部预算仍可提前结束。DeepEvidence 工具次数包括子代理调度、图和数据库工具动作。BioMDT 工具次数统计数据库封装调用。两个计数的粒度写入实验配置说明，资源图另外比较实际 Token 和耗时。

## Benchmark

### 运行协议与产物

`scripts/benchmark.py` 支持 smoke、pilot、single-task、full 和 custom。每个 case × method 使用独立进程和目录。新运行保存选择、非密钥配置、可见输入、官方历史代码提交和项目方法源码快照。续跑要求选择、配置及方法源码一致，已保存的成功、弃答、失败记录均跳过。评分和绘图可独立重算。启动命令集中在 [README](../README.md)。

| 指标 | 计算与能力 |
| --- | --- |
| Exact Match | 官方判分，完全正确题数除以计划题数。评价候选答案整体正确性 |
| Option Precision / Recall / F1 | 逐题对预测和答案集合计算交集占预测、占参考及其 F1，再对计划题目取均值。分别评价所选结论正确性、正确结论覆盖和二者的综合表现。弃答、无效预测及未运行按空集计 |
| Coverage | 有效非空预测数除以计划题数，评价任务完成率 |
| 状态与故障 | 正确、错误、弃答、无效选项、格式错误、模型或进程接口失败、未运行。数据库失败可与有效预测重叠。记录已观察到的失败和重试 |
| Efficiency | 逐题记录后端返回的输入、输出及总 Token、模型调用、工具调用、耗时、重试和可观测缓存命中。按方法和任务聚合均值及运行时间中位数 |

计划分母包括已安排但尚无结果的题目。没有可用运行数据的表格单元留空。效率只用已观察值；被网关中断但未返回 usage 的调用不计入成功响应的 Token 总量。Token 预算于每次调用前根据累计已报告用量检查，最后一次响应可跨过阈值。模型 HTTP 瞬时错误可按共同配置重试。数据库延用公开 GET 遇到 TLS EOF 重试一次的逻辑。数据库内部重试及 DeepEvidence 内部缓存用量只有在日志可见时才可统计。

### 三次真实开发运行

三种方法各执行 CYH33（`preclinical_research_1`）一次，模型为 `gpt-6.2-sol`，请求推理强度为 `low`，同一 OpenAI 兼容后端和相同题干及选项。三条运行均保存有效预测 A，官方 Exact Match 均为 1/1，本题的选项 Precision、Recall、F1 和 Coverage 均为 1/1。

| 方法 | Input Tokens | Output Tokens | LLM Calls | Tool Calls | 耗时（秒） |
| --- | ---: | ---: | ---: | ---: | ---: |
| Direct LLM | 5,702 | 129 | 1 | 0 | 7.973 |
| DeepEvidence (Adapted) | 109,043 | 1,203 | 10 | 8 | 69.538 |
| BioMDT | 84,962 | 15,174 | 10 | 19 | 300.138 |

DeepEvidence 本次真实执行记录包含 BFRS、`search_papers`、`fetch_paper_content`、`add_to_graph` 和 `retrieve_from_graph`。历史真实 CYH33 试跑使用 DFRS 及文献工具。本次另外独立调用官方全文入口，返回该篇研究的 PMC 全文。BioMDT 在本次运行保存四个专业角色、24 条证据及每轮图状态。[本次统计表](../results/benchmark/smoke-sol-low/tables.md) · [历史 DFRS 日志](../results/deepevidence/preclinical_research_1.json)

绘图入口支持 12 张图和 PNG、SVG、PDF。开发产物实际生成 9 类图，两个箱线图因每方法仅一题跳过，命题转移图因无观测到的状态转换跳过，原因保存在 `figures/skipped.json`。论文参考结果另存为独立 CSV 与 Markdown 表，包含 DeepEvidence、Biomni、ToolUniverse 和原文通用 LLM 对照。[开发图表](../results/benchmark/smoke-sol-low/figures/) · [原文结果与口径](published_benchmark_results.md)

## Biological interpretation 的证据接口

`summary.json` 的逐题证据块保存可定位引用、数据库、引用证据节点、推理路径、专业 Agent 激活和贡献、跨角色交接、已传递证据数、上下文不匹配计数及命题状态转移。数据库数和证据数作为过程量。科学质量由核验记录单独衡量。

- **Traceability** 为可定位到该次执行检索记录的唯一引用数除以可解析引用数。BioMDT 的来源检索参数可定位到原始 SQLite 缓存。DeepEvidence 的新执行适配器会存储 PubMed/PubTator 工具返回。Smoke 的 DeepEvidence 原始存档只有子代理摘要、工具调用和图，原始子代理工具返回没有进入该批运行文件，因而自动追溯值留空。
- **Support Rate** 为经核验且获完整支持的关键主张数除以已核验主张数。人工审核逐条比对原文、疾病、物种、模型、干预、读出和比较对象，使用 `supported`、`partial`、`contradicted`、`context_mismatch`、`unverifiable`。本次每种证据方法审核两个关键机制主张，BioMDT 为 2/2，DeepEvidence 为 1/2。DeepEvidence 对 SHP2 的表述超出所复核原文能够支持的范围。整个回答的其他主张尚待覆盖。
- **Cross-source Integration** 为经审核案例中，最终关键推理可定位到至少两类独立且互补来源的案例比例。复核记录为 0 或 1，并描述跨源关联。Smoke 的两个被核验机制均追溯至同一项 HNSCC 研究，两种方法该核验的取值均为 0。

正式核验前在运行目录放置 `evidence_review_plan.json`，内容为预选的九个题号数组，每任务三个。每题每种方法在 `evidence_reviews.jsonl` 中写一行，含 `id`、`method`、`cross_source_integration`、`integration_assessment` 和 `claims`。每条 claim 记录 `claim`、`verdict`、`source`、`excerpt`、`context_assessment`，以及可用的文件和偏移量。重算时加载记录。没有审核的字段保持缺失。Smoke 的审核记录包含实际全文片段与核验范围。[真实核验记录](../results/benchmark/smoke-sol-low/evidence_reviews.jsonl)

## 已知问题

- Smoke 的运行配置、三种预测、工具记录和比分已保存。方法源码快照及 DeepEvidence 逐条检索响应记录在本轮 Smoke 启动后补入框架，使用新目录的后续运行将启用。Smoke 的独立全文核验与初始推理产物分别存档。
- 本次覆盖一题三次推理。三项任务的完整性能、箱线图的真实分布、九题证据核验和批量 API 稳定性待正式实验。
- 网关指标仅统计本地可见信息。公共来源缓存由项目工作区共享，报告含命中情况。正式对比需固定后端配置、来源范围、预算和缓存策略。
