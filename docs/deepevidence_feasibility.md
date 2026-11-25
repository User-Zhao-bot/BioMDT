# BioMDT × DeepEvidence 调研与复现可行性

**建议采用 DeepEvidence 原任务与正式发布的 75 道题。** 以机制与通路推理为主要分析任务，靶点识别和代谢通量作为迁移检验。核心对照采用固定历史实现的 DeepEvidence，在同一模型和同一工具预算下，检验「按候选命题的证据缺口检索」与「按实验条件融合证据」各自是否改善结果。CIViC 路线暂停，原有文件继续保留。

## Problem

DeepEvidence 研究如何跨文献、数据库和通路，把可追溯的局部证据组织为多步结论。BioMDT 可直接沿用三个任务的原问题与候选选项，重点检验模型能否找对证据、解释适用条件、识别表面矛盾。三个任务分别从靶点选择、实验机制理解和代谢趋势推断考查上述能力。论文另评估四个通用医学基准、临床试验设计和证据缺口发现，以及专家审阅的开放题。本项目使用指定三个公开选择题分片，论文其余任务提供方法背景。 [期刊正式版](https://doi.org/10.1038/s42256-026-01266-0) · [正文与补充材料入口](https://pmc.ncbi.nlm.nih.gov/articles/PMC13449190/#supplementary-materials)

## Data

以 HF revision `06b349b24ee18a8d5a2db3e498884d5ad9600f76` 固定下载。官方合集有 7 个配置，本次指定的三个 `test` 分片共 75 条、75 个唯一 ID，子任务内题干各不重复。共同字段为 `id, task_type, question, options, answers, gains, rationale`。靶点和通量另含 `disease, kegg_evidence`，个别疾病字段可空。主输入只传 `question, options`；`answers, gains, rationale, kegg_evidence` 仅供评分或事后审阅。原卷选项文本与顺序照用。 [数据卡与固定版本](https://huggingface.co/datasets/zifeng-ai/DeepEvidence/tree/06b349b24ee18a8d5a2db3e498884d5ad9600f76)

| 官方子任务 | 实测数据 | 参考答案的依据 |
|---|---|---|
| `target_identification` | 25 题，每题 10 项。7 题单选、18 题多选 | 论文用 KEGG 疾病通路的边极性、反向补偿和功能类别构建优先级代理标签。部分发布题也在 rationale 中援引已知转化研究 |
| `moa_pathway_reasoning` | 25 题，每题 5–8 项。12 题单选、13 题多选 | 生物医学情境及候选机制由领域专家依据临床前实验、组学或论文证据整理。考查干预、读出、组织与条件的匹配 |
| `in_vivo_metabolic_flux_response` | 25 题，每题 7 项。1 题单选、24 题多选 | KEGG KGML 的上下游反应、末端产物和反馈循环构成机制推理的代理标签。选项描述假想队列的读出 |

三个原卷实例如下。表中参考来自 Parquet 的 `answers`，待评分输出是所选字母数组与单独的证据说明。

| 原卷 ID | 题意与代表性选项 | 官方参考 |
|---|---|---|
| `target_identification_19` | 三阴性乳腺癌中优先考虑哪个药物靶点。A 为 PARP1 与 BRCA 缺陷背景下的合成致死，C 为 PD-L1，G 为 CHEK1 | `["A"]` |
| `preclinical_research_1` | CYH33 在头颈鳞癌中的抗肿瘤机制。A 为抑制 PI3Kα、减弱 AKT 磷酸化；C 为 ERK 磷酸化阻断及 SHP2 参与这一复合陈述 | `["A"]`，C 的 gain 为 1 |
| `in_vivo_flux_response_2` | 肺癌模型中，哪两类描述最符合 SHMT2 受抑后的强代谢响应。A 为示踪标记持续下降，C 为暂时下降，D 为代谢活性持续受抑 | `["A","D"]`，C 的 gain 为 1 |

`gains` 数组长度正确，但 75 题中有 **6 题的 gain=2 选项集合与 answers 不同**。MoA 是 `preclinical_research_10` 至 `_14`，通量是 `in_vivo_flux_response_13`。评分以发布的 `answers` 为准，6 题保留原样、单列复核，不能用 gain 反推答案。这也意味着分级准确性等附加评价需要明确标签口径。 [数据文件](https://huggingface.co/datasets/zifeng-ai/DeepEvidence/tree/06b349b24ee18a8d5a2db3e498884d5ad9600f76)

## Model

论文正文及 28 页补充信息中的 A.1–A.4、表 1–4、表 9–12 分别给出了编排/子 Agent/图记忆提示词、数据库工具、三项题例，以及开放题和专家 rubric。原系统使用 **Orchestrator → BFRS / DFRS → 汇报与再规划**。BFRS 跨来源展开实体和候选关系，DFRS 沿已发现的机制、文献和引文追查，二者都有独立 LangGraph 工具循环。主 Agent 随进度读写证据图，保留规范标识、观察与出处。补充信息 A.4 已要求保留冲突证据并加冲突组标记，把物种、样本以及 assay 多放在观察文字中。论文 Fig. 5f 的消融显示，仅有多 Agent 分工不足以改善结果。 [原文 Methods、Discussion、Fig. 5](https://pmc.ncbi.nlm.nih.gov/articles/PMC13449190/)

| 核查项 | 源码与复现边界 |
|---|---|
| 历史工作流 | 固定作者迁移说明指向的 `b12439eba3c77a9bab652015b17467c1f5bcf9ce`。论文本体类位于 `biodsa/agents/deepevidence/agent.py`，公开示例是 `scripts/run_deepevidence_agent.py` 和 tutorial。父图根据 tool call 路由，子图追查后将摘要作为 ToolMessage 返回，`biodsa/memory/graph.py` 管理持久图。该提交在发表后，适用于复现公开方法，论文当时的精确实验工件没有完整固定到此提交。 [源码](https://github.com/RyanWangZf/BioDSA/tree/b12439eba3c77a9bab652015b17467c1f5bcf9ce/biodsa/agents/deepevidence) |
| 数据库与依赖 | `schema.py` 把知识库分配给工具组。PubMed、PubTator、Reactome、KEGG、Open Targets、ChEMBL 等由客户端与工具包装层连接。原方法还使用 Docker 内的 Python 查询与分析环境，UMLS 等能力取决于凭据。本机 Python 3.12.14 按历史 `Pipfile.lock` 安装了 208 个解析依赖，LangGraph 1.0.5、LangChain Core 1.2.5、ChromaDB 1.3.7。 |
| 当前实现 | 当前主线为 `1c7f7d1af3f5b93db59afbf6e0fb3c8c587aa864`，原法移到 `legacy/`。`agents/deepevidence` 是 Harbor 迁移版。其搜索循环按预配置工具迭代，仍缺原版模型驱动的独立 BFRS/DFRS 子图，并且图检索结果尚未回传综合。保留为单独基线版本。 [迁移说明](https://github.com/RyanWangZf/BioDSA/blob/1c7f7d1af3f5b93db59afbf6e0fb3c8c587aa864/agents/deepevidence/MIGRATION.md) |
| CLI 后端 | 已登录 ChatGPT 的独立二进制 `~/.local/bin/codex`（0.157.1）支持 `exec --json --output-schema`。使用 `--ignore-user-config` 和账户默认模型完成非交互调用。该界面没有在试跑记录中返回默认模型标识，显式请求的 `gpt-6.2-sol` 与 `gpt-5.4` 均被账户模型目录拒绝，因此当前账号下无法声明与论文 GPT-5 相同。原程序用 LangChain API 的 `bind_tools`，Harbor 用 OpenAI-compatible HTTP；本机适配器通过结构化输出转换角色消息、工具定义及工具结果。本次只用已有登录，没有配置其他模型 API。正式比较前需固定可报告的模型标识，并记录调用数、总 tokens 和延迟。 [CLI 非交互文档](https://developers.openai.com/codex/noninteractive) · [最小适配器](../scripts/deepevidence_smoke.py) |

### 三条真实案例试跑

从原始分片取出如下题目，将题干和原选项传给历史版 `DeepEvidenceAgent`，评分时才读取分开的 `answers`。

| ID | 官方参考 | CLI 预测 | 官方 grader exact match | 观察 |
|---|---|---|---:|---|
| `preclinical_research_1` | A | A | 1/1 | DFRS 检索 HNSCC 中 CYH33 研究及一个不同乳腺癌背景的 CYH33 研究。最终把 AKT 抑制与 ERK/GAB1 区分，并指出选项 C 增加的 SHP2 条件不受该证据支持。图记忆有 2 个带 PMID 观察的论文节点、0 条关系边。 |
| `in_vivo_flux_response_2` | A、D | A、D | 1/1 | DFRS 检索 SHMT2 肺癌论文，区分细胞增殖证据和题目所述的小鼠代谢响应。结论明确标为基于描述的推断。图记忆有 1 个带 PMID 观察的论文节点、0 条关系边。 |
| `target_identification_19` | A | 未生成 | 未评分 | DFRS 入口启动后，CLI 返回账户 usage limit。未写入答案或纳入准确率。 |

前两条各触发一次 DFRS、三个 PubMed 工具调用、图记忆读取与更新，并通过作者的 `harbor_bdr_grade.py` 以原答案评分。各自累计约 22 万输入 tokens、1.3–2.1 千输出 tokens。Docker 客户端连接 daemon 时报告 Unix socket 不存在，源码包装层于是回退到本地 Python 执行。显式调用本账户不支持的模型名会在推理前被拒绝。试跑验证了原版工作流、PubMed 工具、图记忆接口和评分函数的衔接，运行所用模型由 CLI 账户默认选取。 [CYH33 试跑输出](../results/deepevidence/preclinical_research_1.json) · [SHMT2 试跑输出](../results/deepevidence/in_vivo_flux_response_2.json) · [未评分的靶点试跑](../results/deepevidence/target_identification_19_attempt.json)

**BioMDT 优先检验的变化**。在原共享图和 BFRS/DFRS 基础上，增加「候选命题 → 所需证据」表示。角色按基因/靶点、通路/扰动、实验/文献的证据类型工作，任务附带具体缺口，如目标背景下缺少磷酸化观测或比较对象。图中的声明显式记录 `intervention, model, readout, direction, comparator, source`。程序判断对比条件和上下文，保留同条件反向结果供核验；模型提取证据、补检和组织解释。对只有其中一个分句成立的复合选项，例如 CYH33 的 C，应分别核验两个分句。依次比较原调度、仅缺口调度、仅条件融合、两者合用，固定调用与检索预算。消融设计单独报告原方法已有的图记忆与冲突留存能力。

## Benchmark

论文 Fig. 2b 的靶点识别准确率为 DeepEvidence 68%、Biomni 56%、ToolUniverse 40%、通用 LLM 42%；Fig. 3b 的 MoA 准确率为 DeepEvidence 72%、Biomni 44%、ToolUniverse 44%、通用 LLM 52%；Fig. 3d 的通量准确率为 DeepEvidence 80%、Biomni 68%、通用 LLM 60%、ToolUniverse 52%。论文柱图以均值和 95% CI 表示。课程项目主指标采用选项 **exact match**。单选完全命中，多选要求预测与参考集合相等，顺序忽略，非法或重复选项无效。按子任务汇报 25 题准确率，并汇报 75 题总体匹配率。证据链质量使用引用实质支持和条件适用性的定性审核，引用质量不计入选项分数。 [原文 Fig. 2–3](https://pmc.ncbi.nlm.nih.gov/articles/PMC13449190/) · [官方评分函数](https://github.com/RyanWangZf/BioDSA/blob/b12439eba3c77a9bab652015b17467c1f5bcf9ce/scripts/harbor_bdr_grade.py)

当前 Harbor `jobs/deepevidence.yaml` 指向另一枚 HF 修订 `f3e34ee8ccde8ea15c98f55dae871e63ef8bc5b2`，正式 verifier 范围是 13 个子集共 131 条。核对发现指定三组的题干各有 25/25 与原卷相同，但各组在 Harbor 分为 15 fit、5 tune、5 verifier，三组进入该 job 正式计分的合计只有 15 条。20 条 fit/tune 各带 rationale 字段，当前 runner 实际传入 `instruction`，未将 rationale 拼进该字段。原 75 题应直接从原 Parquet 输入，规范封装为 `<BIOMED_FINAL>` JSON，评分端复用作者 grader 并按原 `answers` 判分。该路径复用官方题和评判代码，属于 BioMDT 的论文协议复跑，Harbor 默认 job 使用自己的数据范围。 [Harbor 基准及版本](https://github.com/RyanWangZf/BioDSA/tree/1c7f7d1af3f5b93db59afbf6e0fb3c8c587aa864/benchmarks/biomedicine-deep-research)

## Biological interpretation

- **靶点识别。** A 所依据的是 BRCA 缺陷背景下的 PARP 依赖。OlympiAD 的研究人群为携带胚系 BRCA 变异的转移性 HER2 阴性乳腺癌，该证据的适用范围比题干的泛 TNBC 窄，不能单凭题库答案断言所有 TNBC 或正常组织表达限制。 [PMID 28578601](https://pubmed.ncbi.nlm.nih.gov/28578601/)
- **机制推理。** 原研究确实在药物敏感的 HNSCC 模型中观察到 GAB1/ERK 磷酸化改变，并指出 PI3K/AKT 抑制本身不足以解释抗肿瘤活性。选项 A 是直接作用路径，C 合并 ERK 表型和 SHP2 因果主张，不能仅凭第一句成立而接受整个选项；独立的 SHP2 抑制研究属于另一个干预。这个题目适合检查模型是否把 gain=1 当作整项正确。 [CYH33 原文](https://pmc.ncbi.nlm.nih.gov/articles/PMC12177050/) · [SHP2 独立研究](https://pubmed.ncbi.nlm.nih.gov/36506869/)
- **代谢通量。** 线粒体 SHMT2 与丝氨酸、甘氨酸和一碳代谢相连，但体外追踪显示通量随营养背景变化。A/D 是题库的持续效应代理判断，真实肺癌队列的效应需要相应的示踪与比较实验。 [PMID 38515202](https://pubmed.ncbi.nlm.nih.gov/38515202/)

### 已知限制

作者指出当前知识库覆盖仍不完整，冲突处置主要依赖底座 LLM，缺少概率或置信度校准；研究策略限于 BFRS/DFRS，当前能力未达到多项任务的专家水平，且以文本数据为主。75 题及标注公开，训练重叠可能影响结果。六个 `answers`/gain 不一致项和两条直接浏览过的试跑应在最终评估记录中标记。通量与部分靶点分片使用路径代理标签，生物结论应限于数据和机制推理能力。当前 CLI 运行采用未固定具体 ID 的账户默认模型，无法与论文 GPT-5 结果直接比较；正式基线应固定可报告的模型、工具环境、案例范围和调用预算。
