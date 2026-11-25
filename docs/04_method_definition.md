# BioMDT 方法定义

BioMDT 研究给定癌症背景、体细胞变异和单一候选药物时，如何整合分子、通路、药物和研究结果，推断在该背景下可支持的响应方向。输出包括三类标签之一或 `Insufficient evidence`、可追溯证据链、反向或限制证据、冲突的处置结论以及仍缺少的条件。抗肿瘤活性、组织适用性和机制解释分别记录。

## 输入、输出和共享证据图

输入 `case_id, disease:{doid,name}, variant:{gene_id,transcript,protein_change}, drug:{id,name}, context`。上下文只使用在预测时可知的非结果字段，如临床/细胞系、组织亚型、原发或获得性、既往治疗、单药方案、比较对象和目标终点；缺失值为 `unknown`。输出为 `label, evidence_ids, mechanism_paths, conflict_dispositions, unresolved_gaps`。数值强度只能附带原终点、分母与单位。一个病例可以有合理机制同时缺少可判定的响应标签。

图中的实体节点包括疾病、基因、蛋白/变异、药物、通路/反应、实验模型和来源。事实和推断都作为可引用的声明，有 `subject, relation, object, context, polarity, endpoint, origin, study_id, source_id, locator, excerpt, evidence_kind`。上下文涉及肿瘤本体、组织/亚型、受试模型、基因背景与共变异、既往治疗、暴露、治疗阶段、比较对象和终点。推断记录前提边 ID 和条件。相同三元组、不同实验条件可并存。相同 PMID/试验同一队列及同一结果的转述关联到同一研究结果，避免数据库和论文重复计票。

## 角色与执行

| 角色 | 输入及工具 | 输出 |
|---|---|---|
| 病理 | 疾病 ID、组织/亚型、阶段、样本；固定疾病本体与病例元数据 | 标准疾病及上下位关系；适用上下文、缺失条件 |
| 基因组 | 变异、转录本和现有图；UniProt 特征、HGNC/Ensembl 映射 | 蛋白变异、功能方向、别名及对应依据 |
| 通路 | 蛋白/变异 ID；Reactome mapping、event | 作用链、通路适用范围；未找到的情境边 |
| 药理 | ChEMBL 药物号、配体/靶标；molecule、mechanism、activity | 药物→靶点、机制、体外 assay 粒度 |
| 文献 | 证据缺口、别名、目标条件；冻结 PubMed 索引与文献片段 | 有极性、有终点和出处的临床/实验观察，反例及效应限定 |
| 冲突核验 | 图中重叠或疑似矛盾的声明；原始来源、实体映射与试验元数据 | 支持、反驳、条件差异、同源或尚不能判定；可提出具体追查 |
| 综合与协调 | 病例、证据图、剩余预算 | 待执行查询、最终响应和解释，引用可核实的声明 ID |

### Shared Biomedical Evidence Graph

确定性程序规范化实体、验证引用能回到原始片段、登记来源及实验条件、保留同义/上下位映射等级。精确变异键要绑定参考蛋白或转录本。仅同一残基位置、热点组和具体替换属于不同匹配等级。ChEMBL 的 compound/target、UniProt 的蛋白及疾病的 DOID 都有自己的命名空间。LLM 从论文片段提取条件和关系，提出跨来源连接；未通过实体或引用验证的内容可作为待查假设。

### Evidence-Gap Driven Collaboration

所有病例先建立最低限度的图。决策所需的证据槽为「变异功能」「药物作用」「通路效应」「目标条件下的直接响应」「改变外推结论的冲突/限制」。状态为 `missing / indirect / direct / conflicting`。程序按「实体尚未确定 → 缺同上下文响应 → 高影响冲突 → 机制断点」生成队列，LLM 在预算内把缺口翻译为结构化查询。每个任务携带目标边或槽、已有事实 ID、具体查询条件和剩余预算，相关 Agent 读取同一图并写回。例：药理返回 PI-103 的 molecule 有而 mechanism 空，调度 activity 和文献；病理发现 CRC 与 melanoma 的证据指向不同组织，文献角色检索 BRAF 抑制后在两种背景下的反馈，冲突角色检验临床与临床前的条件。新增高相关事实、冲突已处置、相同查询无新证据或预算截止时，重新决定是否终止。所有调度决定可记录和重放。

### Context-Aware Evidence Fusion

1. 同源合并。比较声明的药物/方案、变体、亚型、疾病阶段、临床与细胞/动物、终点时间、比较对象。临床 ORR 与细胞 IC50 保留不同单位和解释。
2. 只把作用于同一适用范围、方案和可比较终点的相反观察视为候选冲突。明确不相交的条件各自成立；字段缺失则标记为可能冲突。持续效应和早期反应可兼容。`Does Not Support Sensitivity/Response` 和 `Supports Resistance` 保留各自语义。
3. 汇总按预定的匹配与研究设计规则排序。先比较与问题的直接性，再比较终点相关性和研究设计、独立性、样本规模及不确定性。同背景可直接解释响应的人体研究优先用于临床病例。生化靶点/细胞干预证据用于机制及候选解释，组织、终点或阶段不同的结果作为外推边界。Reduced Sensitivity 必须指出具体比较关系；弱或未匹配的证据不能自动转换为 Resistance。
4. 同等级直接证据相互矛盾且现有信息无法解释时，返回未解决冲突和依据；只有机制链、或比较基准缺失时保留弃答。LLM 输出自然语言解释及其事实/推断边界，程序核实标签和边引用有效。

## 调度和结论生成

```text
case = normalize(raw_case)
graph = write(initial_entity_pathway_drug_records, case)
while remaining_budget and graph has actionable gaps:
    tasks = select(derive_gaps(graph, case), remaining_budget)
    proposed_edges = extract(retrieve(tasks), case)
    graph = merge(graph, validated(proposed_edges))
    graph = attach_conflict_dispositions(graph, case)
    stop when the selected tasks produce no new relevant edge
evidence = rank_applicable_independent_observations(graph, case)
output = explain(decide(evidence), ranked_evidence=evidence, graph=graph)
```

初始开发配置最多两轮补证，每轮先列影响结论最大的目标槽，再执行预算内能够消解该槽的查询。证据排序键按变异与方案匹配、目标背景及终点匹配、研究设计和独立来源排列。条件明确不匹配的观察留在机制或外推层，不能为目标响应累计票数。直接观察的效应方向、分母和相反证据先在结构化层登记，然后生成解释。由条件判定器得到「可判定」「需澄清比较对象」「同条件冲突未解决」三种状态；后两种会输出弃答和证据缺口。正式运行前用开发数据冻结匹配门槛和公共预算。

## 与既有方法的区别

- MedRAG 的检索结果在平面上下文中供生成使用。这里每次检索的输入来自共用图中的具体缺边，结果为可重复引用、有范围的声明。
- MedAgents 以文本专家报告、投票及共识更新为中心。结果相反时，BioMDT 先比较陈述适用范围并保留互补证据，再综合目标条件。
- MDAgents 根据题目复杂度选择 solo、团队或层级组。BioMDT 按执行中暴露的证据缺口重调度，记录触发前后的图状态。
- KG-Orchestra 提供文献到证据图的直接相关先例。这里的检验是证据图作为共享工作状态能否改变下一步查询及响应结论。IDAP 的结构证据用于候选药排序，BioMDT 的任务是给定药物在指定背景下的响应。
- DrugAgent 的多智能体职责与药物领域相关，EvoMDT 也研究动态协作与证据驱动会诊。研究比较集中在用具体缺口触发查询、在带上下文的图上判断冲突及量化这些操作的收益。相关工作与源码边界见 [01](01_related_work.md) 和 [02](02_baseline_selection.md)。

## 下一阶段实现顺序

先实现数据导入和统一 case/context/evidence 契约，再冻结可共享的证据索引，接通 Direct LLM 与三个论文候选基线，构建确定性图写入、同源归并和最小缺口调度器。固定上下文对照和原文核验集之后，接入完整角色与消融。Phase 1 的图与病例用于开发契约和保留生物学解释实例。
