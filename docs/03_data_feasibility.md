# BioMDT 数据可行性与接口验证

本阶段冻结了 CIViC、CIViC-Fact 和 GDSC 的官方数据，并保存实际查询到的异构证据。病例候选、核验标注和体外药敏分别对应响应任务、证据核验和外部方向比较。带来源的五个实例见 [试点](../results/pilot/README.md)。

## CIViC 药物响应

### 数据版本和字段

使用 CIViC 官方月度快照 `01-Nov-2026`。`ClinicalEvidenceSummaries.tsv` 有 4,974 条 Evidence Item（EID），25 个字段。同期的 `MolecularProfileSummaries.tsv`、`VariantSummaries.tsv`、`FeatureSummaries.tsv` 分别有 2,006、2,026、1,009 行。关系为 EID 的 `molecular_profile_id` → 分子谱的 `variant_ids` → 变异的 `feature_id` → Gene feature 的 `entrez_id`。变异表另有 HGVS、转录本、参考序列坐标、ClinGen Allele Registry ID，以及该变异的正向单变异分子谱 ID。CIViC 数据为 CC0。 [官方数据发布](https://civicdb.org/releases/main) · [月度证据表](https://civicdb.org/downloads/01-Nov-2026/01-Nov-2026-ClinicalEvidenceSummaries.tsv) · [分子谱数据模型](https://docs.civicdb.org/en/latest/model/molecular_profiles.html)

| 原表字段 | 内容 |
|---|---|
| `molecular_profile`, `molecular_profile_id`, `molecular_profile_civic_url` | 分子谱名称、主键和访问地址 |
| `disease`, `doid`, `phenotypes`, `variant_origin` | 癌种、疾病本体号、附加表型、体细胞或胚系等变异来源 |
| `therapies`, `therapy_interaction_type` | 药物或治疗项，以及 Combination、Substitutes、Sequential 等用法 |
| `evidence_type`, `evidence_direction`, `significance` | 证据问题类别、对所标主张的方向、临床响应类别等效应 |
| `evidence_level`, `rating`, `evidence_status`, `is_flagged` | 证据等级、策展质量评分、审核状态、待关注标记 |
| `citation_id`, `source_type`, `asco_abstract_id`, `citation`, `nct_ids` | 文献或会议 ID、类型、引文、试验号。按 `source_type` 解释编号 |
| `evidence_statement`, `evidence_id`, `evidence_civic_url`, `last_review_date` | 策展证据正文、EID、访问地址和审核时间 |

A 级表示已验证的关联，B 为临床证据，C 为病例研究，D 为临床前证据，E 为推断。癌症分期、用药线数、既往暴露、是否脑转移、比较药物和实验终点没有统一的独立列，须从声明和原文中补录。 [Evidence Level](https://docs.civicdb.org/en/latest/model/evidence/level.html) · [策展规范](https://docs.civicdb.org/en/latest/curating/evidence.html)

### 筛选和计数

| 顺序 | 口径 | 剩余 EID | 本步剔除 |
|---|---|---:|---:|
| 1 | 月度导出 | 4,974 | — |
| 2 | `accepted` | 4,974 | 0 |
| 3 | `Predictive` | 2,913 | 2,061 |
| 4 | `Supports` | 2,521 | 392 |
| 5 | 癌症背景有 DOID，排除泛癌、泛实体瘤和实际出现的非恶性 Chuvash Polycythemia | 2,324 | 197 |
| 6 | 分子谱只有一个变异成员 | 1,936 | 388 |
| 7 | 分子谱为该变异的正向简单谱 | 1,935 | 1 |
| 8 | 关联一个带 Entrez ID 的 Gene feature | 1,645 | 290 |
| 9 | 明确等位变异，具有 `CA` 等位号或带 Sequence Ontology 类型的明确蛋白替换/终止变异 | 716 | 929 |
| 10 | 单个治疗名称，且无多疗法交互类型 | 517 | 199 |
| 11 | 治疗字段指向单一明确药物或命名研究化合物 | 501 | 16 |
| 12 | 仅三个目标响应标签 | 500 | 1 |

全部原始证据按类别为 Diagnostic 500、Predictive 2,913、Prognostic 548、Predisposing 681、Oncogenic 158、Functional 174，按方向为 Supports 4,425、Does Not Support 532、N/A 17。单成员并不保证变异存在，例如 [EID11158](https://civicdb.org/links/evidence_items/11158) 的 `NOT KIT D816V` 仍有一个 KIT D816V 成员。治疗名称也会包裹多个药物，例如 [EID670](https://civicdb.org/links/evidence_items/670) 的 FOLFOX、[EID1057](https://civicdb.org/links/evidence_items/1057) 的 futuximab/modotuximab 混合物。明确的组合例见 [EID1906](https://civicdb.org/links/evidence_items/1906)，同时存在 BRAF V600E 与 GNAS R201C、三药方案。药物类、混合物、放射性碘未指定制剂、疗法和方案单名都排除。研究原文可指定具体试剂时保留，例如 O'Brien 研究中的 PI3Ka/Di。药物活性成分层面合并 imatinib mesylate / imatinib、PI103 / PI-103、regorafenib anhydrous / regorafenib。保留原名供核对。 [PubChem Imatinib](https://pubchem.ncbi.nlm.nih.gov/compound/Imatinib) · [IUPHAR PI-103](https://www.guidetopharmacology.org/GRAC/LigandDisplayForward?ligandId=5701) · [FDA regorafenib](https://www.accessdata.fda.gov/drugsatfda_docs/label/2025/203085s016lbl.pdf)

按 Entrez、等位号（缺失时用 CIViC variant ID）、DOID、规范药物名去重，得到 **418 个独立候选键**，覆盖 **77 个 DOID、61 个基因、230 个基因-等位组合、99 个药物名**。同试验下重复出版保留为来源链接。多个 EID 和文献构成一个键的证据明细。

| 响应标签 | 筛选后的支持 EID | 唯一支持标签的候选键 |
|---|---:|---:|
| Sensitivity/Response | 304 | 254 |
| Resistance | 195 | 156 |
| Reduced Sensitivity | 1 | 1 |
| 合计 | 500 | 411 |

500 条证据的等级分布为 A 14、B 87、C 161、D 235、E 3，含 6 条已接受但带 flag 的记录。同键存在不同 Supports 标签的有 **7 键**。同键同一标签出现 Supports 与 Does Not Support 的有 **5 键**（同时出现两类冲突的有 2 键，共 10 个粗粒度冲突键）。方向不同的行保存在参考数据中。粗粒度冲突需要结合研究对象、标签语义和终点逐条判断。保留任一 A/B 级支持、唯一支持标签且无同标签方向对立时，余 **76 键**。这个数仍含待核对的适应证、治疗线别和合并标志物。

### 有解释价值的真实条件

| 条件 | 来源及含义 |
|---|---|
| 体外与临床不同层级 | BRAF V600E 结直肠癌–vemurafenib有细胞和异种移植支持 [EID99](https://civicdb.org/links/evidence_items/99)，也有篮式试验个别病例证据 [EID5960](https://civicdb.org/links/evidence_items/5960)。在 21 名转移性 CRC 患者的单药 II 期试验，仅 1 例部分缓解，[EID1405](https://civicdb.org/links/evidence_items/1405) 标为 Does Not Support Sensitivity/Response。临床试验、个别病例及特定体外模型对应不同适用范围。 [PMID 26460303](https://pubmed.ncbi.nlm.nih.gov/26460303/) |
| 上下位癌种与共享队列 | Melanoma 的 [EID1398](https://civicdb.org/links/evidence_items/1398) 和 Skin Melanoma 的 [EID1409](https://civicdb.org/links/evidence_items/1409) 同属 BRIM-3（NCT01006980），因此同一研究家族应在同一 split，避免两个 DOID 和两个 PMID 被当作两个独立队列。 [PMID 24508103](https://pubmed.ncbi.nlm.nih.gov/24508103/) · [PMID 21639808](https://pubmed.ncbi.nlm.nih.gov/21639808/) |
| 既往治疗与人群 | 初治转移性黑色素瘤与放射性碘难治、既往 VEGFR 抑制剂暴露的乳头状甲状腺癌应分开表达。后者 [EID1591](https://civicdb.org/links/evidence_items/1591) 和 [EID9018](https://civicdb.org/links/evidence_items/9018) 来自同一出版与试验，队列内有不同既往治疗。 [PMID 27460442](https://pubmed.ncbi.nlm.nih.gov/27460442/) |
| 同病名、不同模型 | ALK R1275Q–TAE684 的 [EID39](https://civicdb.org/links/evidence_items/39) 与 [EID48](https://civicdb.org/links/evidence_items/48) 均源于同一论文。表达该变异的 Ba/F3 细胞可被抑制，人神经母细胞瘤 SMS-KCNR 细胞对其耐受，需在图中保留物种、细胞系、实验系统和终点。 [PMID 18923525](https://pubmed.ncbi.nlm.nih.gov/18923525/) |
| 移植/细胞与药物剂量 | EID99 中 6 株 BRAF V600E CRC 细胞系只有 4 株在所述 IC50 范围内敏感，未响应的 RKO 还带 PIK3CA H1047R。同一简单分子谱不能排除原文中存在的共变异。 [PMID 22180495](https://pubmed.ncbi.nlm.nih.gov/22180495/) |
| 疾病标注与原文对象 | [EID7583](https://civicdb.org/links/evidence_items/7583) 的表中 DOID 为 Langerhans Cell Sarcoma，而声明与原文描述的是 refractory childhood Langerhans cell histiocytosis。该记录需要疾病核验后再进入计分。 [PMID 31513482](https://pubmed.ncbi.nlm.nih.gov/31513482/) |

### 跨癌种候选对复核

以相同 Entrez、精确等位变异和规范单药、不同 DOID、唯一支持标签且标签不同为条件，共发现 **2 组记录候选对，0 组通过严格可比性复核**。

| 候选 | 条件与复核结果 |
|---|---|
| PIK3CA E542K–PI-103。CIVIC-0330 / CIVIC-0334 | CIViC 将同一研究的 HER2 阳性 HCC202（[EID2058](https://civicdb.org/links/evidence_items/2058)，敏感）与 luminal-like KPL-1（[EID8007](https://civicdb.org/links/evidence_items/8007)，耐药）标为同一 E542K。原始补表 Sheet1 的 D38、D33 确认数值为 0.4267 与 7.6233，比例约 17.9 倍。原表 D1 写 mM，CIViC 写 µM，原文正文也以 µM 描述 assay 量级，绝对数须保留单位来源。独立研究 Table 1 记录 KPL-1 为 E545K，HCC202 为 E545K、L866F；HCC202 的 E545K 也见独立测序与 Cellosaurus。两个 DOID 对应乳腺癌总类与亚型，表中的标签差异不能用来评分精确 E542K 的跨癌种推断。 [原始补表](https://ndownloader.figshare.com/files/39893154) · [O’Brien PMID 20453058](https://pubmed.ncbi.nlm.nih.gov/20453058/) · [Elkabets Table 1](https://pmc.ncbi.nlm.nih.gov/articles/PMC3935768/#T1) · [测序 PMID 28356768](https://pubmed.ncbi.nlm.nih.gov/28356768/) · [Cellosaurus CVCL_2062](https://www.cellosaurus.org/CVCL_2062) |
| PIK3CA E545K–PI-103。CIVIC-0314 / CIVIC-0318 | 乳腺癌 MCF7 的 [EID8008](https://civicdb.org/links/evidence_items/8008) 依据活力 IC50（补表 Sheet1 D15 为 1.53，CIViC 记为 µM），NSCLC H460 的 [EID2040](https://civicdb.org/links/evidence_items/2040) 依据 p-AKT 下降、衰老表型及相对 A549 效应，两边是不同研究和终点。该组合提供同变异、同化合物的跨癌种实验线索，缺少用相同 assay 比较的标签。 [PMID 20453058](https://pubmed.ncbi.nlm.nih.gov/20453058/) · [PMID 19513541](https://pubmed.ncbi.nlm.nih.gov/19513541/) |

两种可用于机制展示的辅助比较来自临床文献。第一，BRAF V600E 患者在 dabrafenib 单药一期试验中，CRC 组记录 1/9 确认缓解，推荐二期剂量下转移性黑色素瘤 V600E 组为 15/27 确认缓解。CRC 的 [EID1406](https://civicdb.org/links/evidence_items/1406) 标注 Reduced Sensitivity，比较对象和共同药物必须显式保留。该快照缺少独立 accepted 的黑色素瘤简单谱对应 EID，两人群也非跨癌种随机组，所以只能用作带限定条件的文献对照。第二，vemurafenib 篮式试验的 BRAF **V600**（[EID1574](https://civicdb.org/links/evidence_items/1574)、[EID1576](https://civicdb.org/links/evidence_items/1576)）在 NSCLC 与 CRC 分别为 8/19 和 0/10，属于混合或未知 V600 亚型，保留在探索层。 [Falchook PMID 22608338](https://pubmed.ncbi.nlm.nih.gov/22608338/) · [Hyman PMID 26287849](https://pubmed.ncbi.nlm.nih.gov/26287849/)

### 输入、参考与下一阶段抽样

`data/processed/civic/model_inputs.jsonl` 只有案例 ID、基因、等位编号、HGVS、疾病/DOID、药物。`references.jsonl` 单独保存标签、EID、等级、方向、来源、试验号、证据声明，以及表型和变异来源。`pair_candidates.jsonl` 含标签、EID 与 PMID，仅供评估端。`statistics.json` 记录筛选器计数。后续用 418 键中可核验的病例构建 100～200 条样本池有数量基础，需明确纳入的证据层级和冲突剔除，并按独立研究与分子家族分组。现有 76 条粗筛临床候选不足以支持 100～200 条纯临床案例，单条 Reduced Sensitivity 也不足以估计该类稳定的 F1。对于正式主任务可以先对专家确认的 Sensitivity/Response 与 Resistance 两类评分，将 Reduced Sensitivity、冲突和临床前记录按其生物学条件独立报告。暂时将跨癌种 Pair Accuracy 标为不可估计。 [筛选脚本](../scripts/process_civic.py)

## 公开接口与跨库实体接合

2026-11-25 实际查询返回 HTTP 200。原始 JSON/XML 和请求元数据在 `data/raw/queries/`，每个原始文件对应 `.source.json`。生物学判读与证据边见 [试点报告](../results/pilot/README.md) 和 [证据图](../results/pilot/evidence_graph.json)。

| 数据库 | 实测端点、格式与记录 | 接合和解释范围 |
|---|---|---|
| UniProtKB | `/uniprotkb/{accession}.json`，release 2026_04。P15056 与 P42336 返回 `primaryAccession`、`genes`、`organism`、`comments[FUNCTION]`、`features`。两个等位变异为 VAR_018629、VAR_026173 | 用人类蛋白 accession 接通靶标和 Reactome；由参考序列、残基和替换联合识别 V600E / E542K。PIK3CA E542K 与 E542Q 同位置且可共用 dbSNP 号，不能单凭 rs 号合并。 [UniProt REST](https://www.uniprot.org/help/rest-api) |
| Reactome | ContentService `data/mapping/UniProt/{id}/pathways` 返回数组，P15056 16 条，P42336 60 条。`data/query/{stableId}` 返回 JSON，含 `stIdVersion`、`displayName`、`summation`、`speciesName`。核对 R-HSA-6802948.2、R-HSA-6802912.4、R-HSA-6802938.3、R-HSA-2219528.4 | 映射用于找候选通路，核对具体事件和实体类型后才建边。试点所用一般活化/抑制事件不能区分 CRC 的 EGFR 与甲状腺模型的 HER3 反馈，需补文献及条件。 [Reactome Content Service](https://reactome.org/ContentService/) |
| ChEMBL | `molecule`、`mechanism`、`target` 和 `activity` 返回 JSON。vemurafenib CHEMBL1229517 的 mechanism 995 返回 INHIBITOR、CHEMBL5145、V600E。PI-103 CHEMBL573339 的 mechanism 为 0。IC50 / nM 定向查询对 PI3Kα CHEMBL4005、mTOR CHEMBL2842 分别有 43、22 条，保存各首 10 条 | 药物按 ChEMBL ID 和标准 InChIKey 复核，靶标用 `target_components.accession` 连到 UniProt。PI-103 可用有出处的 activity 补足机制表空缺。应同时检查 assay 描述、条件及所指靶点。生化 IC50 与细胞活力 IC50 使用各自终点。 [ChEMBL API](https://www.ebi.ac.uk/chembl/api/data/docs) |
| PubMed | ESearch JSON 的 `esearchresult.count/idlist`，BRAF/vemurafenib 与 EGFR/HER3 的广查询返回 135 条，保留前 10 条；通过标题/主题查找机制与临床原始研究，再按明确 PMID 用 EFetch XML 保存 12 篇；包括 `PMID`、`ArticleTitle`、`AbstractText`、`ArticleIdList` | PMID 是研究链接，PMCID、DOI 和 NCT 支持同源归并。只看 PMID 不能区分同论文不同队列、药物臂和终点。遇到摘要无所需结论时检查原文/supplement，证据记录保留定位。 [E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25499/) |

映射以 CIViC 的 DOID 和官方变异特征为起点，文献中的组织名、细胞系和疾病标签经原文条件验证后连接。疾病上下位语义、药物别名、批准适应证、共变异和试验标识符都作为显式证据，名称相似不能代替链接。PI-103 的细胞系身份额外使用 Cellosaurus CVCL_2062、CVCL_2094 核对。试点脚本每个数据库可单独运行，只依赖 Python 标准库。

```sh
python3 scripts/query_uniprot.py P15056
python3 scripts/query_uniprot.py P42336
python3 scripts/query_reactome.py R-HSA-6802948 R-HSA-6802912 R-HSA-6802938 --uniprot P15056
python3 scripts/query_reactome.py R-HSA-2219528 --uniprot P42336
python3 scripts/query_chembl.py CHEMBL1229517
python3 scripts/query_chembl.py CHEMBL573339 --activity-target CHEMBL4005 CHEMBL2842
python3 scripts/query_pubmed.py --term '(BRAF[Title/Abstract] AND vemurafenib[Title/Abstract]) AND (EGFR[Title/Abstract] OR HER3[Title/Abstract])' --limit 10 --output data/raw/queries/pubmed/braf-search.json
python3 scripts/query_pubmed.py --pmid 21639808 22281684 22448344 26460303 22180495 29320312 23365119 27460442 20453058 17575152 16697955 28356768 --output data/raw/queries/pubmed/pilot.xml
for cell in CVCL_2062 CVCL_2094; do
  PYTHONPATH=scripts python3 -c 'import sys; from query_common import QUERY_DIR,fetch; name=sys.argv[1]; fetch(f"https://api.cellosaurus.org/cell-line/{name}?format=json", QUERY_DIR / "cellosaurus" / f"{name}.json")' "$cell"
done
python3 scripts/build_pilot.py
```

先获取固定的 CIViC 下载及 PI-103 补充表，再生成病例输入和参考。实时 API 可随版本更新；解释以存档快照为准。

## GDSC 细胞系药敏

本轮使用 Sanger GDSC Release 8.5（2023-10-27）原存档中的拟合药敏表、药物注释和细胞系清单。突变与组织学分别固定为 Sanger Cell Model Passports 的 `mutations_summary_20260724.zip` 和 `model_list_20261013.csv`，两者是独立版本的基因组与模型注释。原文件保存在 `data/raw/gdsc/`，完整下载 URL 见统计文件。来源：[GDSC1 拟合数据](https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.5/GDSC1_fitted_dose_response_27Oct23.xlsx)、[GDSC2 拟合数据](https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.5/GDSC2_fitted_dose_response_27Oct23.xlsx)、[官方字段说明](https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.5/GDSC_Fitted_Data_Description.pdf)、[Cell Model Passports 下载页](https://cellmodelpassports.sanger.ac.uk/downloads/gdsc)、[Sanger 实验方法](https://depmap.sanger.ac.uk/documentation/datasets/drug-sensitivity/)。

| 实际读取范围 | GDSC1 | GDSC2 |
|---|---:|---:|
| 拟合响应行 | 333,161 | 242,036 |
| 唯一细胞系 `SANGER_MODEL_ID` | 970 | 969 |
| 唯一 `DRUG_ID` | 402 | 295 |
| SIDM 连到 Cell Model Passports 元数据 | 970 | 969 |
| COSMIC ID 连到 GDSC 细胞系清单 | 970 | 969 |

化合物注释有 621 行，GDSC 细胞系清单有 1,002 行。Cell Model Passports 模型表有 2,292 条，驱动突变表有 15,025 行、涉及 1,533 个模型。药敏横表每个 `(DATASET, SANGER_MODEL_ID, DRUG_ID)` 只有一个拟合结果。药敏表的 `SANGER_MODEL_ID` 对应模型表与突变表的 `model_id`（SIDM），`COSMIC_ID` 用来独立核对与定位历史细胞系元数据。两份药敏表中，具有可核对的 Cell Model Passports COSMIC ID 的映射均一致。癌种取 `TCGA_DESC` 与模型表的 `cancer_type`，原样保留 `cancer_type_detail`、NCIt ID 和 tissue。样本只取人类细胞系，以 `gene_symbol` 和 `protein_mutation` 精确匹配驱动突变记录，保留 Ensembl 基因 ID、cDNA 注释和突变数据来源。驱动突变表适合筛选阳性细胞系，缺行的基因型仍需独立判定。来源：[历史细胞系注释](https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.5/Cell_Lines_Details.xlsx)、[历史化合物注释](https://cog.sanger.ac.uk/cancerrxgene/GDSC_release8.5/screened_compounds_rel_8.5.csv)、[驱动突变表](https://cog.sanger.ac.uk/cmp/download/mutations_summary_20260724.zip)、[模型表](https://cog.sanger.ac.uk/cmp/download/model_list_20261013.csv)。

### BRAF p.V600E 与 Vemurafenib

在模型突变表中匹配到 90 个 BRAF p.V600E 阳性模型。Vemurafenib 及 PLX4032、RG7204、Zelboraf、RO5185426 等别名在 621 行化合物注释及两个拟合表中均为 0 条，因而这个组合无法在已核查的 GDSC 8.5 文件中做同药验证。PLX-4720 为独立化合物，有 `DRUG_ID` 1036 和 1371 两个实验记录，保留其原名和 ID。来源：[FDA 对 Vemurafenib 的化合物标识](https://www.accessdata.fda.gov/drugsatfda_docs/nda/2011/202429Orig1s000PharmR.pdf)、[PLX-4720 化合物记录](https://pubchem.ncbi.nlm.nih.gov/compound/24180719/)、[两种化合物的对照实验](https://pubmed.ncbi.nlm.nih.gov/24735766/)。

### 跨癌种比较的实际覆盖

表中每项为 **阳性细胞系数 / 拟合 LN_IC50 中位数**，浓度单位为 µM。只在同一筛选版本、同一药物 ID 和相同浓度范围内展示横向对照。表中各组均有完整 `LN_IC50` 和 `AUC`。

| 突变和药物 | 筛选/拟合版本 | 浓度范围 | SKCM 黑色素瘤 | COREAD 结直肠癌 | THCA 甲状腺癌 | BRCA 乳腺癌 |
|---|---|---|---:|---:|---:|---:|
| BRAF p.V600E + Dabrafenib (1373) | GDSC1 / 342 | 0.039063–10 | 34 / −3.141 | 5 / 1.332 | 7 / −2.775 | 1 / −4.502 |
| BRAF p.V600E + Dabrafenib (1373) | GDSC2 / 343 | 0.010005–10 | 38 / −0.875 | — | 7 / 1.800 | — |
| BRAF p.V600E + PLX-4720 (1036) | GDSC1 / 342 | 0.039063–10 | 39 / 0.684 | 7 / 2.415 | 7 / 1.139 | 1 / −1.553 |
| BRAF p.V600E + PLX-4720 (1371) | GDSC1 / 342 | 0.039063–10 | 40 / 1.174 | 7 / 2.043 | 7 / 1.764 | 1 / −0.055 |
| BRAF p.V600E + PLX-4720 (1036) | GDSC2 / 343 | 0.010005–10 | 40 / 0.948 | 7 / 2.193 | 7 / 2.373 | 1 / −0.924 |
| PIK3CA p.H1047R + GNE-317 (1926) | GDSC2 / 343 | 0.010005–10 | — | 5 / 0.684 | — | 8 / −0.301 |

同浓度范围内，AUC 中位数方向与表中两组 LN_IC50 比较一致。Dabrafenib GDSC1 黑色素瘤为 0.162，结直肠癌为 0.746。GNE-317 GDSC2 乳腺癌为 0.607，结直肠癌为 0.711。

GDSC2 的 Dabrafenib 结直肠癌组另有 7 个细胞系，最低筛选浓度为 0.009766 µM，中位数 1.441。Dabrafenib 在 GDSC1 和 GDSC2 间复用 53 个阳性细胞系，PLX-4720 (1036) 复用 63 个，跨版本分析按重复模型处理。甲状腺癌组包含 4 个未分化癌、2 个乳头状癌、1 个滤泡癌，特定临床组织学的匹配须使用细分字段。

GNE-317 的 p.H1047R 阳性样本共有 20 个，提供第二条通路的可比较实验组合。GDSC 药物注释列出 PI3Kα，原始药理研究量化了对 PI3Kα 和 mTOR 的活性，这个差异可用来验证模型是否追踪证据粒度和出处。GDSC2 中 Alpelisib (1560) 对 p.H1047R 和 p.E545K 各有 21 个阳性模型，其中 p.H1047R 的结直肠癌 5 个模型上限为 5 µM，乳腺癌 8 个模型上限为 10 µM，缺少药量范围匹配的乳腺癌—结直肠癌比较。来源：[GNE-317 药理原始研究](https://pubmed.ncbi.nlm.nih.gov/22992516/)。

### 评价用途与局限

- 可开展同药、同突变、筛选条件一致的解释性比较。优先采用 GDSC1 的 Dabrafenib 黑色素瘤—结直肠癌和 GDSC2 的 GNE-317 乳腺癌—结直肠癌。PLX-4720 可用于同一途径的补充验证。
- `LN_IC50` 是以 µM 计的拟合 IC50 的自然对数，越低表示体外达到半数抑制所需的浓度越低。`AUC` 取决于测试浓度区间。GDSC1 的 Dabrafenib 黑色素瘤组有 13/34 条拟合值低于最低测量浓度，结直肠癌组有 1/5 条高于最高测量浓度。后续比较保留越界标记，可用同浓度范围内的 AUC 或对区间外 IC50 做删失处理；统计单位为细胞系，并核查患者来源、组织学、共突变和培养条件。
- 细胞系单药活力可以检验预先写下的体外相对方向。治疗线次、联合用药、临床终点和某条通路的具体反馈机制需独立证据。细胞系规模与研究设计支持本阶段的覆盖检查和后续探索性验证。

复跑命令（需要 `uv` 和 `curl`）：

```sh
uv run --python 3.12 --with python-calamine==0.6.2 python scripts/gdsc_feasibility.py --download
```

输出位于 `data/processed/gdsc/`。`joined_response_rows.csv` 含 372 条逐模型记录，`cross_cancer_cohorts.csv` 含 85 个分层，`summary.json` 记录原文件链接、连接覆盖和各组合总数。

## CIViC-Fact 主张核验与证据定位


下载作者 [v2026.06.09 发布](https://github.com/creisle/civicfact/releases/tag/v2026.06.09)，固定提交 `1e7d58550fedf88eaf8884028cc7dbc703256037`。2025 预印本的 SUPPORTS / REFUTES / NEI 与这版的 SUPPORTS / REVISIONS / NEI 属于不同标注版本。按发布版代码，REVISIONS 指证据相关且主张需要修改。另保留早期专家解释子集，按档案版本评价。 [2025 论文](https://pubmed.ncbi.nlm.nih.gov/41000838/) · [发布格式](https://github.com/creisle/civicfact/blob/1e7d58550fedf88eaf8884028cc7dbc703256037/data_builder/README.md) · [标签逻辑](https://github.com/creisle/civicfact/blob/1e7d58550fedf88eaf8884028cc7dbc703256037/data_builder/src/nli/set_labels_and_reasoning.py)

| 文件和字段 | 实际数据 |
|---|---|
| `data.jsonl.gz`，`claim.content` / `claim.flat` | 12,476 条主张–证据对。train 9,693、dev 1,044、test 1,026、unassigned 713。结构化主张有分子谱、疾病、Evidence Type、Significance、药物、方向等；`civic.claim` 为原始主张，增强后 `claim` 可能变化。 |
| `gold_label_name` / `generated` | SUPPORTS 4,208、REVISIONS 4,300、NEI 3,968。非生成 3,597。Predictive 8,442；test 670 条 Predictive 中 175 条非生成，其余可作为增强后的稳健性检查。 |
| `evidence` / `evidence.flat` / `evidence.source` | 片段内容与定位，来源包括 PMC 全文 5,125、PMC 作者全文 3,068、PubMed 摘要 903、CIViC 二级声明 3,380。文献字段有 PMID、PMCID、DOI、授权标记和题名。 |
| `retrieval.jsonl.gz` / `document_chunks.jsonl.gz` | 1,707 条人工选段的原始主张记录（1,029 Predictive），覆盖 3,551 个标注 span。段元数据有 `meta.section`、`meta.start` / `meta.end`、Hypothes.is 选择 ID。1,546 SUPPORTS、161 NEI。69,764 个候选检索片段来自 3,967 个 PMID，1,546 条支持主张均有对应 PMID 的候选文档。 |
| `reviews` / `conversation` / 专家复核档案 | v2026.06.09 `reviews` 的 983 条记录均标为 bot。人工检索记录中 486 条有非空的 Hypothes.is 片段评论。另下载仓库早期专家复核档案 `expert_reviews_2025-03-21.jsonl`，95 条人工解释，含 `reviews[].reason`、`label`、`original_label` 和审阅者；SUPPORTS 22、REFUTES 27、NEI 46。属于历史单人注释子集，按其原有标签语义使用。 |

实际 Predictive 示例是 `civic.id=10137`、PMID 23995526，FLCN c.1285dupC 胚系变异肾癌与 everolimus 的 SUPPORTS 主张，证据来自原文摘要三段，涵盖诊断、基因型与六线治疗背景。它在最新 verification 数据为 `unassigned`。另一实际例是早期解释档案 EID7560（PMID 28972961）。专家将 Cetuximab 具体药名的主张判作 NEI，因为所选证据对抗 EGFR 抗体的表述不足以确认该具体药物。 [PMID 23995526](https://pubmed.ncbi.nlm.nih.gov/23995526/) · [PMID 28972961](https://pubmed.ncbi.nlm.nih.gov/28972961/) · [专家复核档案](https://github.com/creisle/civicfact/blob/1e7d58550fedf88eaf8884028cc7dbc703256037/manual_reviews/data/doccano/2025.03.21_additional_explanations_2024.03.21/reviews.jsonl)

按当前 CIViC 支持 EID 与 PubMed PMID 双键连通，匹配到 308 个非生成核验记录，覆盖 207 个 CIViC 候选键、226 个 EID 和 130 个 PMID；人工检索匹配 147 条，覆盖 113 个候选键、117 个 EID、78 个 PMID。双键提供来源追踪，仍需检查主张版本、来源内容和证据适用条件。正式评价建议在 CIViC-Fact 单独执行固定主张+证据的 stance 检验，以及同 PMID 语料下的人工标注 span Recall@k。精确率需要对未标注而可能正确的返回片段复核；NEI 统计单列。将可匹配的人工标注用于 CIViC 子集证据审计时，应以文献为单位隔离，避免同 EID 的策展声明或模型可见的结构化主张泄露药物响应标签。CIViC-Fact 数据遵循原文许可，完整快照的再利用按仓库所列最严格许可处理。 [联表脚本](../scripts/inspect_civicfact.py) · [数据许可证](https://github.com/creisle/civicfact/blob/1e7d58550fedf88eaf8884028cc7dbc703256037/data_builder/README.md#data-license)

### 数据复跑

```bash
python3 scripts/download_civic.py all
python3 scripts/process_civic.py
python3 scripts/inspect_civicfact.py
```
