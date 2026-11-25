# BioMDT 基线选择与源码可行性

建议将 **MedRAG、MedAgents、MDAgents** 列为正式候选。三者分别代表平面医学检索、专家协商和自适应协作。**Direct LLM** 是基础对照。DrugAgent、EvoMDT、KG-Orchestra、IDAP 和 CIViC-Fact 提供领域参照，在原任务下各有可复用组件。

## MedAgentBoard 的现成入口

[MedAgentBoard 固定版本 b09dcbb](https://github.com/yhzhu99/medagentboard/tree/b09dcbb11cb2c908e23b83b8b71c566be41326c5) 提供统一风格的 QA 运行器。文本路径接受 `qid`、`question`、`options`，自由文本路径也可无选项。源码同时有图像路径、模型配置和问答日志。原 CLI 从 `my_datasets/processed/medqa/<dataset>/medqa_<mc|ff>_test.json` 读取样本。BioMDT 的运行器应向单案例入口传入标准化问题、选项和可访问证据，参考标签留给评分过程。EHR、文本简化和评测代码中的参考答案路径不需要接入推理。

| 已检出的模块 | 可复用行为 | 原法覆盖和适配要求 |
| --- | --- | --- |
| [`medqa/multi_agent_medagent.py`](https://github.com/yhzhu99/medagentboard/blob/b09dcbb11cb2c908e23b83b8b71c566be41326c5/medagentboard/medqa/multi_agent_medagent.py) | `process_input` → `MDTConsultation.run_consultation`，包含专科招募、医生分析、综合报告、反对意见和多轮修订 | 专科有限枚举，同一阶段处理问题和选项。若直接使用这份代码，标为 **MedAgents (Board)**。论文忠实适配应保留原版独立选项领域选择和分析 |
| [`medqa/multi_agent_mdagents.py`](https://github.com/yhzhu99/medagentboard/blob/b09dcbb11cb2c908e23b83b8b71c566be41326c5/medagentboard/medqa/multi_agent_mdagents.py) | `MDAgentsFramework.run_query` 调度 `_determine_complexity`、`_recruit_experts` 和 `_process_{basic,intermediate,advanced}_query`，保存招募和讨论细节 | 三分支齐备，可采用 **MDAgents (Board)**。各角色的模型可统一。加证据上下文后保留原入场复杂度调度、不加证据缺口驱动路由 |
| [`medqa/single_llm.py`](https://github.com/yhzhu99/medagentboard/blob/b09dcbb11cb2c908e23b83b8b71c566be41326c5/medagentboard/medqa/single_llm.py) | `SingleModelInference.process_item` 支持 zero-shot、few-shot、CoT、自一致性 | Direct 用一次 zero-shot，只读病例条件和响应选项。可增设同一证据包的单模型对照来隔离协作本身的效果 |
| [`utils/llm_configs.py`](https://github.com/yhzhu99/medagentboard/blob/b09dcbb11cb2c908e23b83b8b71c566be41326c5/medagentboard/utils/llm_configs.py) | OpenAI-compatible endpoint、模型键以及角色级别的模型选择 | 将角色调用统一到项目后端，避免选用不同的默认模型。QA 模块无 MedRAG、DrugAgent、EvoMDT 实现 |

本机在隔离的 Python 3.12 环境里实际执行上述三条 `python -m medagentboard.medqa.<module> --help`，三个入口均成功显示参数，可确认模块能导入并进入参数解析。三条源文件都导入 `tqdm`，该项未列入 `pyproject.toml`，运行环境需补装。原作者的 `run.sh` 使用 Bash 关联数组。macOS 环境可直接调用已核查的 Python 模块入口。该检查涉及本地导入和参数解析，原任务得分与付费模型推理未纳入第一阶段验证。

## 三个主要候选

| 候选 | 核心计算逻辑 | BioMDT 适配 | 主要可解释对照 |
| --- | --- | --- | --- |
| **MedRAG** | 问题检索。候选文档按 BM25 或 MedCPT 排序，双检索配置可用 RRF。顺序拼接 Top-k，由单模型生成 | 使用冻结证据快照，统一片段编号，替换语料注册、三类响应提示词和模型生成入口。建议先在开发集确定原论文提供的 BM25/MedCPT/RRF 配置和 k | 单轮平面证据输入是否已足以回答，响应预测提升能否归因于图与后续搜索 |
| **MedAgents** | 分别选择问题和选项专家，先做问题分析，再给选项专家读取。综合、投票、修改报告、单次决策 | 按论文原仓库 `syn_verif` 保留两个专家入口及各自意见。问题变成癌种–变异–单药和明确条件，选项为响应空间。仅换任务提示、证据包与模型调用 | 区分文本讨论形成共识与证据级冲突判定 |
| **MDAgents (Board)** | LLM 初判复杂度。低复杂度单人、中复杂度单组讨论、高复杂度层级多组。最终报告 | 将 QA 输入改成 BioMDT 案例，统一所有角色模型，输出标签、必要条件、证据编号和复杂度分支。可复用 Board 三级拓扑 | 比较一次性按题目难度分流与由证据缺口持续触发协作 |

### 原始实现和依赖

**MedRAG** · [7599a728a28789fd601728c08d313b1148051f41](https://github.com/gzxiong/MedRAG/tree/7599a728a28789fd601728c08d313b1148051f41)。[`src/medrag.py`](https://github.com/gzxiong/MedRAG/blob/7599a728a28789fd601728c08d313b1148051f41/src/medrag.py#L182) 的 `MedRAG.medrag_answer` 是 Python 调用入口，`src/utils.py` 实现 `Retriever`、`RetrievalSystem.retrieve`、RRF `merge`。`src/data` 含语料处理脚本，提示模板在 `src/template.py`。依赖包括 FAISS 1.7.4、Pyserini 0.22.1、Transformers 4.44.2、sentence-transformers 2.2.2 及 tokenizer，BM25 原路径使用 Lucene，密集检索需模型与索引。旧版本 pin 与本机 Apple Silicon/Python 3.12 的完整安装尚待验证。应优先确保使用相同的索引算法和评分方式。源码支持显式传入 `snippets`，但 `MedRAG.__init__` 在 `rag=True` 时已经构建 `RetrievalSystem`。如在统一后端先检索再传上下文，应从检索实例拆开调用，或使用独立生成适配器。默认 OpenAI 名称判断只给 GPT-3.5/4 系列设置上下文窗口，统一后端需要显式设置实际预算。固定用单轮入口，仓库另有后续迭代版 `i_medrag_answer`。

**MedAgents** · [aaeff0499e169b41faf810cbca59504e3ee2788c](https://github.com/gersteinlab/MedAgents/tree/aaeff0499e169b41faf810cbca59504e3ee2788c)。`inference.sh` 调 `run.py --method syn_verif`。[`utils.fully_decode`](https://github.com/gersteinlab/MedAgents/blob/aaeff0499e169b41faf810cbca59504e3ee2788c/utils.py#L6) 是协作主体，`prompt_generator.py` 给每步角色模板，`data_utils.py` 加载 MedQA 并解析选项、票和报告，`api_utils.py` 处理旧模型接口。仓库有 MedQA 测试 JSONL 和提示样例。依赖固定 OpenAI 0.27.4、torch 2.0.0、NumPy 1.23.3 等，当前项目环境缺少原入口的若干依赖。保留原提示和调度，统一模型调用与序列化。参数需显式传入：例如原论文一般将协商最大轮次设为 5，`run.py` 默认 3，且默认只处理索引区间 `[21, 50)`。

**MDAgents** · [3adbd760ca809b4e7b0c1085d68314b6e7d91e1b](https://github.com/mitmedialab/MDAgents/tree/3adbd760ca809b4e7b0c1085d68314b6e7d91e1b)。原入口 [`main.py`](https://github.com/mitmedialab/MDAgents/blob/3adbd760ca809b4e7b0c1085d68314b6e7d91e1b/main.py) 按 `utils.py` 的难度判定分支运行，依赖 OpenAI 1.14.2、Google Gemini SDK、pptree、termcolor、prettytable 等。Google SDK 被源码直接导入但未列于 `requirements.txt`。当前 checkout 中，复杂度模型固定用 `gpt-3.5`，`Agent.chat` 把其他 OpenAI 模型别名派发到 `gpt-4o-mini`，`main.py` 仅当 `--dataset medqa` 才保存样本结果，且未提供论文 RAG 消融的检索实现。因此用 Board 三分支加同一模型调用器可省去入口及模型映射改造。将共享预检索标记为 BioMDT 适配配置。原 README 给出数据链接，代码仓库未直接附上相应数据 JSON。

## 可复用的领域工作

| 方法与固定版本 | 源码和依赖 | 迁移判断 |
| --- | --- | --- |
| **DrugAgent-v1** [6e30ac45222f3b6d223ac3bbfe446b267bd1900f](https://github.com/inoue0426/DrugAgent-v1/tree/6e30ac45222f3b6d223ac3bbfe446b267bd1900f) | `agents/integrate_agent.py --csv …` 读取 `Drug,Gene`。`DTIAgentSystem` 注册 ML、搜索、KG 工具并提交 AutoGen 群聊。包括 DeepPurpose 模型文件、图数据和小样本 CSV，`environment.yml` 固定 pyautogen 0.2.31、DeepPurpose 0.1.5、RDKit 等。参考论文的 Bing Search 已退役，当前 v1 活跃调用 `google_search`，需要 Google API/CSE 配置，源代码里的 Bing URL 与活动调用路径须区分。 | DTI 本身可参考分路取证。若迁移到响应分类，需另设癌种与变异、替换 ML/图上的 DTI 分数含义、按响应终点重写搜索与推理提示。v1 作者标明废弃，替换搜索后只能称修改版。由于任务改造幅度大，暂不列主基线。[微软 Bing Search 生命周期](https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement) |
| **EvoMDT 原仓库** [KesselZ/EvoMDT](https://github.com/KesselZ/EvoMDT) | 原论文所引 GitHub 链接返回 404，Git remote 返回 Repository not found。官方源码、依赖与 commit 无法核查。原文真实回顾性病例需申请。 | 作为方法参照。即使可取得作者核心提示，复现原本体知识库、病灶输入和演化评估仍依赖原数据与检索配套。 |
| **OpenEvoMDT** [a3fa7c8db74e25dd59e52bf33113feef1687688b](https://github.com/yhzhu99/OpenEvoMDT/tree/a3fa7c8db74e25dd59e52bf33113feef1687688b) | 非官方实现。Python 3.12+、OpenAI SDK、Pydantic、torch、BERTScore 和 ROUGE。入口 `python main.py run-case` / `run-benchmark` / `evolve`，`evomdt/pipeline.py` 编排五角色，`consensus.py` 有安全否决和确定性兜底，`evolution.py` 有反馈状态。README 与实现均给出默认关闭检索的运行路径。 | 可以用其生物医学任务合同接同一证据快照，保留五角色和协调流程，以 **OpenEvoMDT-derived** 单独报告。开启原文式检索和反馈演化仍有较大差距。 |
| **KG-Orchestra** [aa35f377651dc407a4506cdd9d6854b203d2813e](https://github.com/Fraunhofer-SCAI-Applied-Semantics/KG-Orchestra/tree/aa35f377651dc407a4506cdd9d6854b203d2813e) | `pdm run python -m kg_orchestra`。`__main__.py` 组装 Ollama、Qdrant、文献和实体匹配，`agents.py` 实现段落评价、路径构建、三元组校验，`neo4j_io.py` 管写回，输出可选 CSV，仓库有 NADKG 示例。依赖本地模型以及 Qdrant/SQLite 文献与实体数据。 | 可对照证据图扩展、极性校验及原文溯源。固定输入药物的响应输出和上下文比较仍需独立定义，与扩图指标分别评估。 |
| **IDAP** [1be155846b62c067084a7fdfdce2f564ec9dea49](https://github.com/joonan-lab/IDAP-pipeline/tree/1be155846b62c067084a7fdfdce2f564ec9dea49) | `main_pipeline.py --maf … --cancer …`。代码要求 OncoKB token、MafAnnotator、PubMed token、TxGNN 根目录与数据。附 NSCLC MAF 样本、ChEMBL 药名表，四源模块齐全。`merge_all_results` 实现样本内百分位及加分。论文还固定了 [Zenodo 归档](https://doi.org/10.5281/zenodo.19301367)。 | 候选优先级可用于另立排序实验。数据只给候选药，也可以提取其可获得证据，但要计算响应标签仍需新增目标函数和方向证据。 |
| **CIViC-Fact** [1e7d58550fedf88eaf8884028cc7dbc703256037](https://github.com/creisle/civicfact/tree/1e7d58550fedf88eaf8884028cc7dbc703256037) | `data_builder` 含 Poetry/Snakemake 构建、CIViC 提取、原文链接、句子抽取和负例处理，`experiments` 有训练/评估，`manual_reviews` 有审核。可直接读取 `builds` 压缩发布数据。 | 可独立评估有出处的科学主张核验、句段检索和解释支持度。真实核验标签与受控合成负例来源分别保留，后者不能当作观测药物响应。 |

## 公平实验接口

三种论文方法均从同一病例输入和冻结证据集合开始，使用同一模型标识、模型后端和最大可用预算。MedRAG 用原单轮检索结构。MedAgents 与 MDAgents 采用同一标准 Top-k 起始证据，报告名称中注明共享检索，保留原协作拓扑。BioMDT 可在同一快照内重查，重查消耗相同的证据和计算上限。记录实际模型调用、输入/输出 token、证据检索次数、回答耗时和输出有效率。公平对照允许报告各法预算消耗，较少调用本身也是结果。

参考答案文件和 CIViC 原记录不进入任何模型输入。同一 PMID 的训练、开发与测试归属以及参考文献可见性应按 benchmark 规则固定。基础 Direct 只读结构化病例。增设单模型加同一证据包时，可进一步比较证据可见条件下协作的贡献。

## 已知局限

源码核对证明了可用入口和迁移所需改动。MedAgentBoard 仅完成无模型的入口检查，旧仓库依赖与基座服务在本机尚未完成端到端推理验证。MedAgents、MDAgents 和 MedAgentBoard 当前固定版本未发现仓库级许可文件，汇报时可链接源码。若是直接复制代码并公开发布，需先确认许可，按公开论文独立实现仍可作为候选。KG-Orchestra 期刊可读声明为 Apache 2.0，固定仓库 README 写 MIT，且未检出独立许可文件，合并源码前应以作者确认的许可为准。
