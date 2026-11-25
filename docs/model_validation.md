# BioMDT Phase 2.1：Model 调试与端到端有效性验证

## 当前验收

BioMDT 的六角色运行、证据图、缺口调度、上下文融合和官方评分均已完成开发验证。三题各自最后一次 Model 阶段端到端试跑均产出有效预测。CYH33 选 A，靶点识别选 A，代谢通量选 A、D，均得到官方 Exact Match 1/1。对应记录位于 [最新 Model 开发验证](../results/sol_low/tls_retry_validation/)。

| 开发题 | 最终运行目录 | 证据数 |
| --- | --- | ---: |
| CYH33 | `preclinical_research_1` | 17 |
| 靶点识别 | `target_compact_literature` | 31 |
| 代谢通量 | `flux_cardinality` | 11 |

靶点题的模型网关 524 在最终试跑中经一次重试恢复。三题均属于开发暴露题，正式性能和成本结论留待 Benchmark。Phase 3 同配置的三方法结果见 [Benchmark 报告](benchmark_summary.md)。

## 早期开发记录

以下记录使用较早的代码、提示或模型配置，用于解释修复依据。其中的弃答、空图与接口故障属于对应历史运行。

## 运行范围

仅使用此前已暴露的 `preclinical_research_1`、`target_identification_19` 和 `in_vivo_flux_response_2`。模型输入来自 `data/processed/deepevidence/test_inputs.jsonl`，参考答案由独立评分入口读取。API 配置仅通过单次进程环境变量提供，密钥未写入日志或文档。后端返回的模型标识为 `gpt-6-luna`。

DeepEvidence 官方历史源码版本为 `b12439eba3c77a9bab652015b17467c1f5bcf9ce`。本轮使用明确标记的 `project` 预算档位，即主搜索轮 1、主 Agent 动作 5、子 Agent 动作 3。它保留 Orchestrator、BFRS/DFRS 调度、搜索工具、文献抓取和图记忆，但不是作者默认配置。作者配置仍为主搜索轮 5、主 Agent 动作 20、子 Agent 动作 5，可通过 `--budget-profile author` 选择。

## 故障与修复

### 证据响应解析与图写入

旧图写入器在此前真实 BioMDT 运行中得到 11 个原子命题，却未得到证据节点。原始模型记录已离线回放，证明 `claim_evidence` 中嵌套文献记录能够依据 PMID 关联到已有命题，图从 17 个节点、28 条边增长为 32 个节点、52 条边。回放文件保存在 `results/biomdt/replays/preclinical_research_1-claim_evidence-replay.json`。

本轮真实 Agent 响应还暴露了其它返回结构：`evidence`、`claims`、`results`，以及 `interpretation`、`evidence_status`、`supports_claim` 等字段。规范化器现在将这些结构统一转换为证据记录，保留 stance、事实/推断类型和上下文，并只接受同轮查询结果中实际出现的来源 ID。解析失败、来源不匹配、缺字段和数据库查询异常分别写入运行诊断。

CYH33 修复后日志中有 6 条证据，证据 ID 为 E0001–E0006，来源均为真实 PubMed PMID，图关系包含实体参与证据、证据支持命题以及证据派生自文献。target-identification 的一次真实响应曾返回未映射 claim ID 和不同证据正文键，解析器补齐字符串证据、解释及 note 字段后，重新运行写入 5 条有来源证据。代谢案例还验证了顶层 `source_ids` 数组展开，避免因来源为空丢弃可追溯文献证据。

### 专业 Agent 路由与动态协作

初始实体提取从可见题干和候选命题中识别基因、蛋白、疾病和药物，再根据命题文本推导 Genomics、Pathway、Drug 和 Literature 需求。Coordinator 输出的 `entity_updates` 与 `query_terms` 经过类型检查和归一化，结构化查询计划不会再被转成 Python 字典文本作为关键词。

每轮只执行一个专业角色。图状态重算后，Coordinator 读取未解决命题并从未尝试的角色/查询组合中选择下一步。查询签名由角色、命题和该角色相关实体组成，相同查询不会重复，不同实体参数仍可再次查询。CYH33 的真实协作顺序为 Genomics → Drug → Pathway → Literature，协作消息保留上轮证据缺口和后续任务。target-identification 顺序为 Genomics → Literature → Pathway → Literature。代谢案例调用 Pathway 与 Literature。

### 上下文融合与决策

共享图分别记录每条证据的命题、来源、实验背景、直接性、读出和效应方向。不同癌种或模型的证据不会被当作同条件冲突；明确的上下文不适用信息作为不足证据保留。AND 复合选项要求全部原子命题得到支持，NOT、OR 和 COMPARISON 按图中的命题状态计算。证据缺失不自动变成反驳。

CYH33 检索到的若干证据来自卵巢癌代谢研究，而题目询问 HNSCC。模型在证据记录中标明疾病背景或读出不匹配，Decision 因此弃答。代谢案例所检索记录来自 SHMT2 抑制剂的体外研究或其它癌种，并未报告肺癌小鼠队列的 tracer labeling，因此没有将机制背景冒充为题目要求的直接实验结果。

## 初期三个开发案例

| 案例 | BioMDT Agent / 图 | 预测 | Exact Match | 调用开销 |
|---|---|---|---:|---|
| `preclinical_research_1` | Genomics、Drug、Pathway、Literature；11 个命题、6 条证据，来源和命题均可追溯 | 弃答 | 0/1 | 10 次模型调用，16 次工具调用，75,731 tokens，258.71 秒 |
| `target_identification_19` | Genomics、Pathway、Literature；10 个命题、5 条证据，图记录多项数据库事实及文献证据 | 弃答 | 0/1 | 8 次模型调用，12 次工具调用，75,790 tokens，319.29 秒 |
| `in_vivo_flux_response_2` | Pathway、Literature；7 个命题、0 条证据节点。最新 Agent 输出提供了 `relevant_observations` 和 `claim_assessments`，但未给出命题级证据关联 | 弃答 | 0/1 | 5 次模型调用，6 次工具调用，32,080 tokens，80.08 秒 |

BioMDT 三例最终记录合计使用 23 次模型调用、34 次工具调用和 183,601 tokens。代谢案例的最终日志位于 `results/biomdt/phase2_1/final_attempts/flux-01/`。该案例另有一次模型返回不符合计划对象结构的失败记录，保留在 `results/biomdt/phase2_1/runs/`。缓存复用仅减少数据库重复请求，当前兼容后端每次 Agent 调用仍单独提交上下文。

Direct LLM 在三个案例各调用一次模型，没有使用知识工具，预测分别为 A、A、A+D，三例均通过格式验证。单题评分文件位于 `results/biomdt/phase2_1/scores/`。

DeepEvidence 在 CYH33 案例执行 Orchestrator → BFRS → PubMed 搜索 → `fetch_paper_content` → 图记忆 → 最终综合，输出 A，官方 Exact Match 为 1/1。该运行共 11 次模型调用、9 次工具调用、127,261 tokens。BFRS 实际调用了 `fetch_paper_content`，并检索到 PMID 40533463 的 HNSCC 机制信息。历史 Codex CLI 运行由 DFRS 获取相同论文并得到具体实验内容。当前 API 运行证明原方法的搜索与文献抓取语义可用，但本次调度选择 BFRS，且单搜索轮项目预算没有复现历史 DFRS 路径。该差异已保留在运行日志中。

| 方法 | CYH33 | target-identification | metabolic flux |
|---|---:|---:|---:|
| Direct LLM | 1/1 | 1/1 | 1/1 |
| DeepEvidence | 1/1 | 未运行 | 未运行 |
| BioMDT | 0/1 | 0/1 | 0/1 |

这些分数仅是已暴露开发案例上的运行验证，不是 Benchmark 性能结果。

## 图、日志与评分

- 运行记录：`results/biomdt/phase2_1/runs/`。
- 独立图文件：`results/biomdt/phase2_1/graphs/`。每个文件包含节点、关系边、证据、命题和最终状态。
- 预测与评分：`results/biomdt/phase2_1/*_predictions.jsonl`、`results/biomdt/phase2_1/scores/`。
- DeepEvidence 记录与评分：`results/deepevidence/phase2_1/`。
- 数据库查询缓存：`data/processed/biomedical_evidence.sqlite3`。每次运行日志同时保存各工具参数、来源 ID、缓存命中、返回记录和错误。

评分保留官方 Exact Match。附加统计把弃答、非法选项、格式错误、接口错误和模型错误单独计数；该批早期的三条 BioMDT pilot 为弃答 3、格式错误 0、接口错误 0、模型错误 0。另一次代谢案例重试被单独记为模型接口/输出错误，不替代该案例的最终记录。DeepEvidence CYH33 为完成预测 1，评分器报告 Exact Match 1/1。

## DeepEvidence 忠实性与运行边界

适配器仍调用历史 Agent 和原生工具，通过 OpenAI function calling 承接工具选择，不把方法降为单次 RAG。运行日志中观察到 BFRS 调用 `fetch_paper_content`，最终图记忆使用原工具接口。原始工具响应及官方执行 JSON 保存在 DeepEvidence 运行记录中。

本轮 API 试跑的输入 Token 高于历史 Codex CLI CYH33 成功运行记录，不能据此宣称成本已降低。主要来源是每轮携带累积的 DeepEvidence 消息、重复的工具 schema、BFRS 历史以及文献内容。Codex CLI 当前登录状态为未登录，因此本轮使用当前已授权的 OpenAI 兼容后端。两者后端并非同一 API 执行环境。

本轮实际知识 API 有 HTTP 400：KEGG `find_gene` 与 PubTator `annotations`。错误记录在工具调用日志中，相关查询没有伪装成空的成功结果。UniProt、Open Targets、Reactome、ChEMBL、KEGG 部分操作、PubMed 搜索/抓取均有实际返回记录。

## 初期诊断及当时的验收条件

BioMDT 的真实 Agent 输出格式仍不统一。target-identification 已写入 5 条证据，但图中命题状态仍不足以区分候选选项，Decision 因此弃答。代谢案例的模型通过 `relevant_observations` 和 `claim_assessments` 报告了有出处的上下文信息，却没有将观察关联到 claim ID，图写入器因此不伪造命题链接。Coordinator 还有一次返回列表形状导致模型运行错误，入口已区分并记录该状态。缺少命题级关联时 Decision 偏向弃答，因此当前仍不能与 DeepEvidence 的推断式选择能力作可比评估。部分试跑工具请求也有 HTTP 400。

完成以下修复并以真实模型日志验证后，再考虑完整 Benchmark：

1. 让 Coordinator 与各专业 Agent 遵循同一结构化证据输出契约，响应记录携带有效 claim ID、真实检索来源 ID、原始摘要/解释、事实或推断性质及上下文。
2. 修复并验证 KEGG 与 PubTator 的参数格式，记录实际成功响应。
3. 让 Decision 能在有出处的间接机制证据上作出带不确定性的推断，同时保留直接证据与条件匹配要求。
4. 以相同模型可见信息和适当资源预算复跑三个 pilot，至少确认 target-identification 能写入可追溯证据，CYH33 能稳定完成跨 Agent 协作。
5. 明确 DeepEvidence 正式对比采用作者默认预算还是固定项目预算，并对三个方法使用相同的输入格式及可比调用预算。

## 验证命令

运行脚本只处理指定 pilot 或显式的 `--pilot-only` 输入。DeepEvidence 预算档位由 `scripts/run_deepevidence.py --budget-profile author|project` 选择。全套回归测试覆盖数据处理、评分、证据图、来源校验、命题状态、路由及运行预算配置。

## gpt-6.2-sol 开发复验

使用 OpenAI 兼容后端，模型指定为 `gpt-6.2-sol`，请求推理强度为 `low`。两题均沿用已暴露的 DeepEvidence 输入。证据需要通过命题 ID 和同轮检索来源校验。

- 文献检索优先组合干预或候选基因与题干疾病。药物机制题可从 PubTator 注释定位公开 PMC 文章，再缓存 BioC 原始响应并向 Literature 提供三个相关结果段落，保留 PMID、PMCID 和段落偏移量。
- Genomics 和 Pathway 查询将常见蛋白别名规范为基因符号。KEGG 命中人类基因后读取基因详情。靶点题从可见选项恢复候选基因符号，并优先使用题干中的特异疾病名称。
- 图融合优先使用模型明确填写的结构化上下文，缺项时才使用同条证据的扁平字段。靶点比较按题干标准逐项判断，预测型问题的结论区分实验观察和机制推断。
- 可选命题复核遇到网关超时会沿用首轮计划及本地拆分，并记录该事件。

`results/sol_low/focused_retrieval/` 保存了检索修复的真实运行。CYH33 的 Genomics、Literature、Drug、Pathway 分别写入 4、12、4、5 条证据。靶点题运行至最终决策，三个角色共写入 6 条证据。这一批两个预测均为弃答。

上下文和靶点检索修复后的结果保存在 `results/sol_low/context_ranking/`。CYH33 选 A，官方 Exact Match 为 1/1。靶点题完成作答流程，三个角色写入 6 条证据，Decision 记录了候选靶点正常组织表达、肿瘤依赖性与临床证据中的比较缺口，最终弃答。两题均无模型接口错误。

CYH33 的全文端到端运行保存在 `results/sol_low/full_text/preclinical_research_1/`，同样选 A，官方 Exact Match 为 1/1。Genomics、Drug、Literature、Pathway 分别写入 4、5、12、5 条证据。Decision 引用 Literature 的 E0010 与 E0011，后者可追溯到 PMID 40533463 的全文结果，并据 E0014 与 E0015 保留选项 C 中 SHP2 原子命题的缺口。上下文同义表达修复另用这批真实证据回放，结果保存在同目录的 `context_replay.json`。最终代码通过 78 项回归测试。

### 靶点比较的候选覆盖

旧靶点运行只检索前两个基因，且按全局 PMID 上限截断，候选间的资料覆盖不均。改造后按可见选项中的目标符号和题干疾病逐个发起 PubMed 检索，每个候选取一篇相关性排序靠前的论文，按工具容量分批抓取，避免末尾候选因全局截断丢失。Decision 使用有出处的观察和选项所给前提对照各项标准。资料能区分相对领先者时可给出暂定排序，缺失测量仍留在解释中。

`target_identification_19` 的真实复验选 A，官方 Exact Match 为 1/1。运行对 10 个候选均发起检索，进入模型的摘要共 6 篇，Genomics、Literature 和 Pathway 分别写入 7、12、1 条证据。Decision 引用 E0008–E0010 比较 PARP 抑制在特定亚群中的证据，并引用 E0017 讨论最接近的候选 VEGFA，保留正常组织表达等维度的资料缺口。一次四篇摘要的批量请求遇到 TLS 断开，独立重试返回全部四篇并写入缓存。该批摘要没有参与本次模型决策。运行用时 416.47 秒，共 8 次模型调用和 94,052 tokens。详细日志及评分在 `results/sol_low/candidate_ranking/target_identification_19/`。全套回归测试通过 79 项。

### 传输恢复与三题复跑

公开数据库 GET 请求遇到 TLS EOF 时重试一次。回归测试覆盖 URL 错误包裹 TLS EOF 的情形。此前失败的四篇 PubMed 摘要以空缓存请求，返回 HTTP 200 并取回全部四篇。兼容模型后端遇到 HTTP 524 时也重试一次，成功响应的调用日志记录重试次数。

代谢题原复跑选 D，评分 0/1。题干的 “which two” 原先没有进入选项数校验。修复后从题干识别两个选项的要求，端到端复跑选 A、D，评分 1/1，Pathway 与 Literature 写入 11 条证据。CYH33 复跑选 A，评分 1/1，四个专业角色写入 17 条证据。两题工具日志均无错误。运行输出位于 `results/sol_low/tls_retry_validation/`。

靶点题的两次复跑在模型网关返回 HTTP 524。最终采用精简的 Literature 输入，保留每篇摘要的 PMID、标题、摘要片段和对应命题，去掉重复的选项与检索元数据。最终复跑在一次 Literature 网关自动重试后完成，选 A，评分 1/1，无数据库工具错误，写入 31 条证据。该次运行耗时 521.52 秒，成功响应合计 133,251 tokens。评分与实际运行记录位于 `results/sol_low/tls_retry_validation/target_compact_literature/`。

三题各自最后一次端到端复跑均有有效预测，均通过官方 Exact Match 评分。全套回归测试通过 82 项。靶点题的 524 已在最终复验中恢复，网关仍有响应时间波动。
