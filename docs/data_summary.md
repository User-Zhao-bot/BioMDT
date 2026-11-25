# BioMDT Data 环节

## 数据范围

本项目沿用 DeepEvidence 官方测试数据的三个子任务，共 75 条记录。原始 Parquet 保存在 `data/raw/deepevidence/`，数据集 revision 为 `06b349b24ee18a8d5a2db3e498884d5ad9600f76`。处理脚本保留官方题目 ID、问题文本、候选项文本及顺序，不改写题目。

| 子任务 | 条数 | 单选 | 多选 | 每题候选项数 | 每题正确项数 |
|---|---:|---:|---:|---|---|
| `target_identification` | 25 | 7 | 18 | 10 项：25 题 | 1 项：7；2 项：15；3 项：3 |
| `moa_pathway_reasoning` | 25 | 12 | 13 | 5 项：10；6 项：6；7 项：3；8 项：6 | 1 项：12；2 项：1；3 项：2；4 项：7；5 项：3 |
| `in_vivo_metabolic_flux_response` | 25 | 1 | 24 | 7 项：25 题 | 1 项：1；2 项：8；3 项：16 |
| **总计** | **75** | **20** | **55** | 5–10 项 | 1–5 项 |

![各任务单选与多选构成](../results/data/deepevidence/task_answer_format.png)

![各任务候选项数分布](../results/data/deepevidence/candidate_option_distribution.png)

官方题目并非单一癌症药物响应数据集。靶点识别含炎症、神经退行性疾病、代谢病及肿瘤等背景；MOA 任务聚焦药物作用机制、临床前发现和实验机制判断；体内代谢通量任务覆盖胰腺癌、胶质母细胞瘤及一般癌症代谢场景。原始记录中的疾病字段在靶点任务有 19 个忽略大小写后的值，在代谢通量任务有 5 个，MOA 任务没有独立疾病字段。跨 50 条有 KEGG evidence 的记录，参考解释涉及 59 个不同的 KEGG gene ID、109 个不同的 pathway 文本值和 120 个不同的 biological-process 文本值。这里的通路和过程数量按原文字符串计数，未做生物医学本体归一化。

官方数据没有统一结构化的药物实体列。药物、基因、疾病和机制可能出现在问题、候选项或参考解释的自然语言中，因此数据准备阶段不将字符串提及强制映射成实体 ID，也不将带有标签的信息注入模型输入。

## 标准化文件

`data/processed/deepevidence/test_inputs.jsonl` 是模型唯一可读的数据文件，每行包含 `id`、统一任务名 `task_type`、`question` 和按官方顺序排列的 `options`。其中不含 `answers`、`gains`、`rationale`、`kegg_evidence` 或 disease 字段。

`data/processed/deepevidence/references.jsonl` 独立保存 `answers`、`gains`、`rationale`、原始 `source_task_type`，以及存在时的 `kegg_evidence` 和 disease。评价器在推理后才读取该文件。六条 `answers` 与 `gain=2` 选项不一致的记录完整保留于 `label_anomalies.json`，主评分按官方 `answers`，不按 gains 重写标签。

| 字段/文件 | 内容 | 用途 |
|---|---|---|
| 原始 Parquet | 官方完整记录 | 可追溯输入与标签来源 |
| `test_inputs.jsonl` | ID、任务、原问题、原选项 | 后续所有模型统一输入 |
| `references.jsonl` | 官方答案、gains、解释及结构化证据 | 仅评价和人工审阅读取 |
| `label_anomalies.json` | 6 条答案与 gain-2 差异 | 标签质量审计，保留官方主标签 |
| `pilot_exposed_items.json` | 3 条此前查看或试跑题 | 区分全量协议与未暴露题结果 |
| `statistics.json` | 任务、答案数、选项数及证据字段统计 | 报告与图表的数据源 |

三个 `pilot_exposed` ID 是 `target_identification_19`、`preclinical_research_1` 和 `in_vivo_flux_response_2`。后续结果应同时报告完整 75 题官方协议和排除这三题后的未暴露子集，开发试跑不计作正式实验结果。数据准备脚本每次运行都会重新生成暴露清单和统计。

## 真实题目示例

以下示例只展示模型可见的问题及其需要的知识，不在报告中展示参考答案。

### Target identification

| ID | 问题要点 | 解决所需知识 |
|---|---|---|
| `target_identification_15` | 在溃疡性结肠炎背景下，从 10 个候选基因中选出两个可调节炎症、改善结局的靶点。 | 炎症因子及其受体/信号轴、疾病相关证据、靶点可干预性与临床验证强度。 |
| `target_identification_17` | 为 2 型糖尿病选出 3 个可调节疾病进程的治疗靶点。 | 胰岛素信号、葡萄糖稳态、遗传与患者通路证据，以及小分子或生物制剂可成药性。 |
| `target_identification_19` | 官方靶点选择题，曾进入 Codex CLI 开发试跑但因用量限制没有产出可评分答案。 | 作为开发暴露题记录，不用于代表性模型结果；完整原题见输入文件。 |

### MoA and pathway reasoning

| ID | 问题要点 | 解决所需知识 |
|---|---|---|
| `preclinical_research_0` | 判断首个进入临床试验的国产 PI3Kα 抑制剂的选择性、临床前活性和药物性质。 | PI3K 亚型选择性、PIK3CA 突变模型、异种移植药效、药代和安全性研究，并区分 PI3Kα 选择性抑制剂与 pan-PI3K/PI3K-mTOR 药物。 |
| `preclinical_research_1` | 判断 CYH33 在头颈鳞癌中的抗肿瘤机制。 | PI3Kα–AKT、GAB1/ERK 等机制及肿瘤类型限定的原始文献证据；需避免把其他癌种的免疫研究外推到 HNSCC。此题为试跑暴露题。 |
| `preclinical_research_2` | 选择可验证两个分子在同一通路中机制联系的实验设计。 | 时间序列磷酸化、遗传扰动、互作检测和通路报告实验的因果解释边界。 |

### In vivo metabolic flux response

| ID | 问题要点 | 解决所需知识 |
|---|---|---|
| `in_vivo_flux_response_0` | 在 GLUD1 抑制的谷氨酰胺依赖型胰腺癌模型中，选择预期呈现最佳代谢通量响应的小鼠队列。 | GLUD1 介导的谷氨酸到 α-酮戊二酸转化、谷氨酰胺补充 TCA、同位素示踪和旁路补偿。 |
| `in_vivo_flux_response_1` | 判断 SLC2A1/GLUT1 抑制后，哪些体内肿瘤队列反映持续且转运依赖的通量抑制。 | 葡萄糖转运、示踪物标记、时间持续性及替代碳源/代谢旁路的区分。 |
| `in_vivo_flux_response_2` | 根据 SHMT2 抑制判断肺癌小鼠队列的代谢响应。 | 丝氨酸-甘氨酸/叶酸一碳代谢、核苷酸合成、示踪动态及体外机制向体内模型外推的限制。此题为试跑暴露题。 |

## 生物医学知识源与实体关联

已通过公开接口完成小规模查询，HTTP 成功响应及原始内容保存在 `data/processed/biomedical_evidence.sqlite3`，可读 JSONL 快照保存在 `data/raw/biomedical_queries/cache_export.jsonl`。接口统一由 `scripts/biomedical_evidence.py` 的 `BioKnowledgeTools.query(database, operation, **params)` 调用。缓存键由数据库、操作和规范化查询参数确定；返回信封记录请求 URL/状态、查询参数、检索时间、原始响应、来源 ID、版本信息（接口提供时）和轻量记录。数据库没有提供版本号时记录为 null，不用记录发布日期代替版本号。

| 数据库 | 已验证内容及返回结构 | 主要关联标识符 | 适用边界 |
|---|---|---|---|
| UniProt | REST JSON；基因搜索/蛋白条目，含 accession、gene、蛋白名称和物种；查询头返回 release `2026_04`。 | UniProt accession，如 BRCA1 `P38398`。 | accession 可用于 Reactome 映射，也可与 ChEMBL target component 中的蛋白 accession 关联。 |
| Open Targets | GraphQL JSON；target/disease 搜索命中及 target details，可返回 Ensembl ID、approved symbol、protein IDs、pathway 字段。 | Ensembl Gene ID、EFO disease ID、UniProt protein ID。 | 名称搜索需要检查候选命中，不能把搜索排序首位视为人工确认的实体匹配。 |
| Reactome | ContentService JSON；可通过 UniProt accession 获取 pathway 列表，并按 stable ID 取详情。 | UniProt accession、Reactome stable ID（如 `R-HSA-...`）。 | pathway 条目中的 `releaseDate` 是该记录日期，不是 Reactome 数据库版本；实体映射不等价于疾病特异性机制证据。 |
| KEGG | REST 文本 flat-file；`find` 返回多个 gene 命中，`get` 返回 ENTRY、SYMBOL、NAME、ORGANISM、PATHWAY 等字段。 | KEGG gene ID（如 `hsa:672`）、KEGG pathway ID（如 `hsa05224`）。 | 搜索命中需结合 ID、符号和物种消歧。接口返回的通路成员关系不自动证明某癌种中的耐药或药物响应因果关系。 |
| ChEMBL | REST JSON；分子搜索可得 ChEMBL molecule ID，mechanism 得 action type、机制、target ChEMBL ID，target details 含 target components。 | ChEMBL molecule ID、target ChEMBL ID、蛋白 UniProt accession。 | 可建立药物-机制-靶点-蛋白链路；活性记录受实验体系和测定条件限制。 |
| PubMed | NCBI E-utilities JSON/XML；检索 PMID，抓取题名、摘要和 DOI。 | PMID、DOI。 | 摘要证据可定位文献，精确实验条件可能仍需全文或补充材料。 |
| PubTator | PubTator 3 JSON/BioC JSON；返回文献、实体标注及实体间关系。 | PMID、NCBI Gene ID、MeSH/化学实体标识符。 | 实体共现或自动抽取关系需要回到原文核对语境、方向和实验条件。 |

跨库连接的典型链路为：基因符号经 UniProt/NCBI Gene/Ensembl 解析到稳定基因或蛋白 ID；UniProt accession 映射到 Reactome pathway；Open Targets 使用 Ensembl ID 和 EFO ID 连接靶点与疾病；ChEMBL molecule ID 连接药物机制和 ChEMBL target ID，再由 target components 的 UniProt accession 接入蛋白知识；文献由 PMID/DOI 连接 PubMed 与 PubTator，PubTator 中的 NCBI Gene、MeSH 或化学实体提供候选交叉引用。KEGG 的 `hsa:` ID 与 pathway ID 可连接 KEGG 本体内部的基因和通路记录。名称映射均保留候选与原始记录，确认实体时依据稳定 ID 和物种，不把文本相似直接当作关系证据。

结构化知识库适合提供蛋白功能、靶点、通路成员、药物作用机制和文献实体标注。癌种/模型特异的反馈机制、补偿代谢、耐药因果和实验响应通常需检索并阅读原始研究；通路映射或 PubTator 自动抽取本身不能替代此类证据。当前接口验证为公开 API 的小规模可用性检查，不代表所有字段对所有实体均完整。

## 评分与统一预测接口

预测文件为 JSONL，每行为 `{"id":"...","prediction":["A"]}`；单选和多选统一用选项代码数组表示。缺失预测可将 `prediction` 设为 null，或不提交该 ID。评价入口为 `scripts/evaluate_deepevidence.py`，底层直接加载官方 `harbor_bdr_grade.py`。

主指标为 Exact Match Accuracy，即官方参考集合与预测集合完全相同的题目数除以该子集题目总数。单选题要求唯一选项完全一致；多选题对比集合，因此选项顺序不影响评分，漏选或多选均为错误。非法选项由官方 grader 判为错误；无有效预测按缺失处理并留在分母中。报告分任务准确率和 75 题整体准确率。该指标评价最终选择与官方标签的一致性，不直接评价证据质量或生物学解释正确性。

本项目测试覆盖正确单选/多选、错误选项、多选漏选、多选多选、非法选项和缺失预测，另验证输入与参考答案 ID 一致、模型输入不含标签、官方评分函数实际被调用。**本阶段只验证评分程序，不运行正式模型实验。**

## 运行方式

在项目根目录执行：

```bash
python scripts/prepare_deepevidence_data.py
python scripts/plot_deepevidence_data.py
python scripts/export_evidence_cache.py
python -m pytest -q tests
```

查询数据库的命令入口示例：

```bash
python scripts/query_biomedical.py uniprot entry --params-json '{"accession":"P38398"}'
```

原始 Parquet、标准化文件、隔离答案、七个来源的查询封装及评分入口已具备下一阶段复现 DeepEvidence Baseline 的数据接口。Baseline 仍需在下一阶段按作者运行环境和方法入口执行；本阶段未运行整套模型评测。

## 已知限制

- DeepEvidence 三个子任务覆盖靶点优选、机制判断和体内代谢通量推理，和“癌症相关异构证据整合”有交集，但并非全部题目都属于肿瘤或药物响应场景。遵循 Follow 论文的设计时，主结果应保留官方三任务，肿瘤/机制相关子集可作为预先定义的分层分析。
- 六条 `answers` 与 `gains` 不一致的记录可能影响基于收益分级的次级分析。主指标按官方 `answers`，记录保存在异常文件中。
- 官方参考解释中存在带有论证性陈述的自然语言和 KEGG 派生字段。它们只供评价后解释审阅，不可作为检索语料、缓存证据或 Agent 上下文。
- 两条已评分试跑各累计约 223,172 和 230,192 输入 token，第三条受账户用量限制中止。调用日志表明每轮都携带较大的系统提示、工具定义与累积消息历史。下一阶段应控制历史长度、只返回命中段落/摘要及稳定出处、避免重复回传完整工具 schema，并统计各轮调用 token；当前未重构模型后端。
