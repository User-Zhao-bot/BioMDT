# BioMDT 相关工作

BioMDT 的输入是癌症背景、精确变异和已给定的单药。输出是该背景下的响应方向、适用条件和可回查的证据。靶点结合、候选药排序、临床方案推荐与这一任务有关，各自的输出和参考答案不同。跨癌种方向差异、同背景证据冲突、靶点到表型的证据缺口，是区分这些方法和 BioMDT 的三个问题。仓库版本、源码入口和接入判断见 [基线选择](02_baseline_selection.md)。

## MedAgents · Tang 等 · ACL Findings 2024

- **问题、输入与输出**　用免训练的多学科协作提高零样本医学推理。输入问题和选项，输出选项、解释及协商日志。原论文在 MedQA、MedMCQA、PubMedQA 和六个医学相关 MMLU 子集（解剖学、临床知识、大学医学、医学遗传学、专业医学、大学生物学）比较 QA Accuracy，即选中参考答案的比例。该指标覆盖作答能力，原报告和意见案例用来观察纠错过程。
- **算法与证据**　从问题和答案选项分别招募领域专家。问题专家先独立分析，选项专家读取问题分析后判断各选项。汇总者形成共享文本报告，各领域专家投票同意或反对。反对者给出修改意见，报告更新，迭代到共识或达轮次上限，由决策角色输出。外部文献检索、证据溯源和条件相容性未进入计算。分歧单位是对报告的同意度。
- **迁移**　保留问题分析、选项分析、汇总和反对意见修订。把选项改成三类响应，把共享证据包作为可选外部上下文，使所有角色可查相同的证据编号。原版 `fully_decode` 和 MedAgentBoard 的科室会诊实现均已定位，后者将问题与选项合在医生分析阶段。BioMDT 在证据断言和实验条件上识别冲突，再调度补证。[论文](https://aclanthology.org/2024.findings-acl.33/) · [方法与提示词](https://arxiv.org/html/2311.10537v4) · [原仓库](https://github.com/gersteinlab/MedAgents)

## MDAgents · Kim 等 · NeurIPS 2024

- **问题、输入与输出**　按病例复杂度选择个体、专家组或跨组团队，处理文本、图像和视频医学推理。输入问题、选项及相应模态数据，输出答案、分析以及协作分支。十个数据集覆盖 MedQA、PubMedQA、MedBullets、JAMA、DDXPlus、SymCat、Path-VQA、PMC-VQA、MIMIC-CXR 和 MedVidQA。Accuracy 衡量是否选对或判对。共识分析用 Shannon 熵衡量某轮代理之间的意见分散度。时延和调用成本衡量不同协作分支的资源需求。
- **算法与证据**　Moderator 先按问题复杂度分流，Recruiter 招募专家。低复杂度由单角色作答，中复杂度由专家初步作答、互评和复审，高复杂度由多个小组分工并向上汇报，经最终决定汇总。角色用文本历史和分组报告交换信息。论文另比较 Moderator 复审与 RAG，主要分流由题目驱动。组内异议由对话、复审或共识处理，评估熵可以反映趋同。
- **迁移**　把病例和答案空间替换为癌种、精确变异、药物和三类响应，保留三级分流与分支拓扑。原版和 MedAgentBoard 均有代码。与 BioMDT 的核心区别在于分流决策：MDAgents 入场时选择推理组织，BioMDT 在证据图更新后按具体缺失关系和可比性继续取证。[论文](https://proceedings.neurips.cc/paper_files/paper/2024/hash/90d1fc07f46e31387978b88e7e057a31-Abstract-Conference.html) · [算法与消融](https://arxiv.org/html/2404.15155) · [原仓库](https://github.com/mitmedialab/MDAgents)

## MedRAG · Xiong 等 · ACL Findings 2024

- **问题、输入与输出**　系统评估医学问答中的语料、检索器、生成模型和上下文长度。问题文本触发零样本检索，问题、选项和 Top-k 片段输入单模型，输出答案。实现同时返回片段和分数。MIRAGE 共 7,663 题，来自 MMLU-Med、MedQA-US、MedMCQA、PubMedQA* 和 BioASQ-Y/N。Accuracy 衡量答案准确度。分别改变 k 和正确片段位置可观察证据量、摆放位置与作答的关系。
- **算法与证据**　可在 PubMed、StatPearls、Textbooks、Wikipedia 或四库合并的 MedCorp 上检索。原文比较 BM25、Contriever、SPECTER、MedCPT。多检索器可用 Reciprocal Rank Fusion，按各排名的倒数得分相加。检索片段以平面文本拼到提示词，由同一生成模型解释并作答。相反证据可以同时进入上下文，由生成模型结合提示处理。
- **迁移**　采用原仓库单轮 `medrag_answer` 的检索与生成逻辑，将项目证据快照序列化为编号片段并换成三类响应的输出契约。BioMDT 额外记录断言的适用条件，并由缺口触发后续取证。单轮 MedRAG 是检验这些机制是否超出一般 RAG 的参照。[论文](https://aclanthology.org/2024.findings-acl.372/) · [项目与语料](https://gzxiong.github.io/benchmark-medical-rag/) · [原仓库](https://github.com/gzxiong/MedRAG)

## DrugAgent · Inoue 等 · 2025 预印本

- **问题、输入与输出**　输入药物名或 SMILES、目标基因或蛋白，输出各通道的药物–靶点相互作用（DTI）分数、综合分数和理由。评估采用 Anastassiadis 等的激酶抑制剂生化活性数据，最终抽取 5 组各 50 个配对。Precision 衡量预测相互作用里有多少为真，Recall 衡量已知相互作用被找到的比例，Specificity 衡量正确排除非相互作用的比例，F1 平衡 Precision/Recall。AUROC 衡量跨阈值的区分能力，AUPRC 衡量按分数排序时对稀少阳性相互作用的发现质量。论文同时报告时延、令牌用量和费用。
- **算法与证据**　协调者让 ML、KG、Search 三路输出可合并的分数与理由。ML 用预训练 DeepPurpose。KG 用药物–蛋白图的直接边或限跳路径，综合路径长度与节点度。Search 按药名和靶点查文献结果，对共现和相互作用关键词计分并生成摘要。推理代理用 CoT/ReAct 审查数值和证据，协调者整理最终分数。原文示例展示推理代理在 ML 低分与较强图路径同时出现时解释各路证据并聚合分数。
- **迁移**　v1 的 AutoGen 协调和证据格式可供参考。DTI 分数主要表达结合或相互作用，肿瘤响应还涉及癌种、功能反馈、实验终点和治疗背景。一个有高 DTI 分数的药物可以在多个癌种产生不同响应，增加癌种字段无法弥补这一目标差异。[2025 指定版本](https://arxiv.org/html/2408.13378v4) · [v1 源码](https://github.com/inoue0426/DrugAgent-v1)

## EvoMDT · Liu 等 · npj Digital Medicine 2026

- **问题、输入与输出**　将多癌种患者结构化病灶记录转换为可审阅的 MDT 方案，整合分期、治疗、安全、随访与出处。原文评估 MedQA、MedQA-Cancer、MedMCQA-Cancer、MedQuAD、MedQARo、ROND，以及肺腺癌、乳腺癌、肝细胞癌、淋巴瘤回顾性病例和 405 份单盲医生评估病例材料。
- **算法与证据**　诊断、治疗、安全、监测和协调五角色交换结构化报告。指南、论文和病灶结构经过本体对齐及混合检索，保留证据出处。协调者按病情动态调整角色权重，以语义分歧、临床风险和实施影响评估分歧程度，执行安全优先的层级处理。反馈用于演化调整。
- **评价**　多选 Accuracy 衡量答案命中。BERTScore 和嵌入余弦相似衡量与专家文本的语义相近，ROUGE 衡量词面重叠，模型综合评分评估方案对齐。指南一致性、加权方案一致性、证据可追溯率和安全违规率分别对应指南吻合、重要方案要素吻合、来源可查和风险规则违反。单盲评分覆盖安全伦理、效率、完整性、临床适当性、证据运用及患者中心性。耗时描述给定结构化病例后交付完整方案的速度。
- **迁移**　EvoMDT 的有据协调与 BioMDT 有实质交集。EvoMDT 汇总角色方案及临床风险，BioMDT 的判断单元是带癌种、变异、方案、时序和终点的响应断言。原文病例数据受访问限制，原仓库目前不可访问，第三方替代只能作为独立适配。[论文全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12873204/) · [出版社参考稿](https://www.nature.com/articles/s41746-025-02304-8_reference.pdf) · [作者所引仓库](https://github.com/KesselZ/EvoMDT)

## MedAgentBoard · Zhu 等 · NeurIPS 2025 Datasets and Benchmarks

- **问题、输入与输出**　在同一基准中对比传统模型、单 LLM 与多 LLM 协作。任务输入及输出包括文本/图像问题与回答，文献文本与通俗摘要，结构化 EHR 与死亡或再入院风险，以及分析需求与可执行工作流。QA 的多选准确率衡量选项命中，自由文本由 LLM 裁判和参考文本对比。MedQA、PubMedQA、PathVQA、VQA-RAD 为对应数据。通俗摘要用 Cochrane、eLife、PLOS、Med-EASi、PLABA，ROUGE-L 衡量最长公共子序列重叠，SARI 衡量增加、删除和保留的词是否符合参考简化。MIMIC-IV 和同济 TJH 的 EHR AUROC 衡量跨阈值区分，AUPRC 衡量阳性少时的排序质量。工作流由专家按数据、统计或建模正确性、图表与报告质量评估。
- **方法与迁移**　QA 中代理用文本交换分析，分别沿用 MedAgents、MDAgents、ColaCare、ReConcile 等不同机制。分歧处理继承具体实现。QA/VQA 代码提供现成的分支、共识和单模型入口，适合支撑公平对照。它的实验动机也适用于 BioMDT：协作方式有价值需要同时匹配任务、模型和计算量。药物响应标签、外部生物学证据池和条件冲突评价需由本项目建立。[论文](https://proceedings.neurips.cc/paper_files/paper/2025/hash/d59aa09699530c00d4b875a883876641-Abstract-Datasets_and_Benchmarks_Track.html) · [全文与附录](https://arxiv.org/html/2505.12371) · [仓库](https://github.com/yhzhu99/medagentboard)

## KG-Orchestra · Mohamed 等 · Knowledge-Based Systems 2026

- **问题、输入与输出**　以人工整理的种子三元组和图模式为输入，补充可回溯的有向机制路径，输出扩充图、支持或反驳段落和需审核的关系。
- **算法与证据**　先混合检索文本片段并聚合到父段落，代理评估相关性，证据不足时回退 PubMed/PMC。Path Builder 提出有向路径，Schema Aligner 对齐类型、关系及极性，实体匹配用已有节点或 UMLS CUI，Hop/Triplet Evaluation 校验证据支持、语义方向及生物合理性，Fixer 尝试按证据修正，无解边留待人工审核。不同角色交换结构化段落、路径及评价。种子与新增边都保留引文。
- **评价与迁移**　图扩充在 Nelivaptan–阿尔茨海默病（NADKG）和微生物干预–肠脑轴（ProPreSyn-GBA）测试。预印本以 TREC-COVID、NFCorpus、SciFact 和内部 SCAI-Triplets 对比检索表现，nDCG@10 衡量将相关片段排到前十中靠前位置的能力。三元组由模型批量判断并由专家抽样，分别评估生物合理性、方向、因果性、实体类型和原段落是否支持。路径级评估问题可解性、顺序连通和关系因果性。模块消融比较模式对齐前后的实体类型与关系数量以及边质量。与 BioMDT 重叠最强的是缺证回退、结构化路径和三元组修正。BioMDT 推断给定药物在特定癌种的响应方向，比较研究层级及作用条件。[期刊论文](https://www.sciencedirect.com/science/article/pii/S0950705126020423) · [作者预印本全文](https://www.researchgate.net/publication/400934021_KG-Orchestra_An_Open-Source_Multi-Agent_Framework_for_Evidence-Based_Biomedical_Knowledge_Graphs_Enrichment) · [作者工作流说明](https://www.scai.fraunhofer.de/en/business-research-areas/bioinformatics/students-blog/26-05-2026.html) · [仓库](https://github.com/Fraunhofer-SCAI-Applied-Semantics/KG-Orchestra)

## IDAP · Ryu 等 · Bioinformatics 2026

- **问题、输入与输出**　输入癌种与体细胞变异 MAF，输出患者层的候选药排名、证据及相关试验。目标是扩大精准肿瘤学证据覆盖，供研究者审阅和优先排序。
- **算法与证据**　OncoKB 提供变异级注释，PubMed 提供癌种和基因查询中药名提及计数（药名来自 ChEMBL 词表），TxGNN 派生图提供关联评分，ClinicalTrials.gov 提供癌种和候选药试验元数据。模块用表格汇合，样本内按百分位转换三个逐药得分，再加人工设定的策展、多源和试验奖励。源共识提高候选排序，试验登记和词频本身没有响应方向。
- **评价与迁移**　50 个体细胞变异样本覆盖五种癌症，含内部及 CPTAC 数据。报告候选覆盖、Top-k 多源支持和试验关联比例，并用基因–癌种匹配的 CIViC 做外部 Top-k 命中和首次命中排名。这些结果衡量候选生成、来源覆盖及排序优先级。直接迁移到固定候选药的响应分类会改变排序任务，保留作跨源汇合与弱证据解释的参照。[论文](https://academic.oup.com/bioinformatics/article/42/5/btag300/8675120) · [仓库](https://github.com/joonan-lab/IDAP-pipeline) · [论文归档](https://doi.org/10.5281/zenodo.19301367)

## CIViC-Fact · Reisle 等 · 2025 预印本

- **问题、输入与输出**　针对 CIViC 的结构化癌症变异主张，找出已链接来源文献中的支持或反驳句，再判断主张是否获支持并提供解释。标注包括文献句子、表格和标注解释，正负数据亦可来自 CIViC 修订或受控改写。作者说明 2026.06.09 发布版的主张核验标签为 `SUPPORTS`、`REVISIONS`、`NEI`，句段检索版另存人工标注位置和元数据。[发布版说明](https://github.com/creisle/civicfact/blob/1e7d58550fedf88eaf8884028cc7dbc703256037/data_builder/README.md#using-the-released-dataset)
- **算法与证据**　在已知论文内拆分和检索片段，再将主张和检索上下文交给模型做证据判断。这里的反驳是主张与给定证据不一致。Accuracy 衡量核验标签正确性，mAP@5 衡量文中正确证据出现在检索列表前部的情况。审核分流实验统计标记比例、审核中的问题发现率和预计错误捕获比例。
- **迁移**　已发布脚本和数据可支撑独立的文内证据检索和核验。与 BioMDT 仅在能按证据项编号、PMID、变异和治疗上下文确认同一条主张时建立关联。预测任务参考标签单独维护。[2025 全文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12458922/) · [PubMed 版本记录](https://pubmed.ncbi.nlm.nih.gov/41000838/) · [仓库与数据](https://github.com/creisle/civicfact)

## BioMDT 的技术区别

| 模块 | 已有最相关实现 | BioMDT 要测试的可区分机制 |
| --- | --- | --- |
| Shared Biomedical Evidence Graph | KG-Orchestra 有带出处的有向图、类型对齐和边校验。DrugAgent 用固定 DTI 图。EvoMDT 保存决策证据 | 同一断言可以挂多条证据，分别显式携带癌种、模型、药物方案、时序、终点和对照。来源观察与综合推断分别入图，支持在病例间比较 |
| Evidence-Gap Driven Collaboration | MDAgents 的复杂度分流。KG-Orchestra 的缺证回退与修复。MedAgents 的报告反对和修订 | 由任务必须的实体、观测、作用路径与条件匹配状态触发具体角色和查询。增加、修订证据后重新检测是否还缺目标背景的解释 |
| Context-Aware Evidence Fusion | EvoMDT 的动态角色权重和风险优先。DrugAgent 的来源分数融合。KG-Orchestra 的边级证据校验 | 先比较同一响应主张的适用条件和终点，再依据直接性、可比性、研究层级及独立证据综合。跨癌种方向变化、跨终点差异和同条件矛盾各有独立解释 |

研究贡献应落在可验证的组合机制。关键对照是给定同一快照和同一基座，分别测量单轮检索、文本协商、复杂度路由与条件化证据图在响应分类、跨癌种成对判断、证据支持和冲突定位上的差异。
