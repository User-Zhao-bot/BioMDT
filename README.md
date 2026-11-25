# BioMDT

BioMDT 评测多智能体整合异构生物医学证据的能力。任务、数据和主评分沿用 DeepEvidence。运行说明和最近开发验证见 [Benchmark 报告](docs/benchmark_summary.md)。

## 环境与 API

需要 Python 3.13、Git 和 curl。从空目录开始可执行以下命令。初始化脚本会下载固定版本的官方数据与评分源码，生成 75 题的独立推理输入和评分文件。DeepEvidence 的受限适配允许公开文献工具在本地执行，Docker 为可选环境。

```bash
git clone https://github.com/User-Zhao-bot/BioMDT.git
cd BioMDT
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python scripts/setup_benchmark.py
python -m pytest -q
cp .env.example .env
# 编辑 .env，填写自己的 Key 与兼容接口根地址，地址末尾省略 /v1
source .env
```

初始化时使用 [官方数据版本](https://huggingface.co/datasets/zifeng-ai/DeepEvidence/tree/06b349b24ee18a8d5a2db3e498884d5ad9600f76) 和 [BioDSA 历史提交](https://github.com/RyanWangZf/BioDSA/tree/b12439eba3c77a9bab652015b17467c1f5bcf9ce)。安装依赖和运行测试无需模型 API 凭据。

更换 API 时修改 `.env` 中的地址、密钥、模型和推理强度。后端支持 temperature 时可设置 `OPENAI_TEMPERATURE`。默认不发送 temperature。使用新的运行目录。超时、重试、并发、预算和工具范围在 [benchmark.json](configs/benchmark.json) 中配置，可复制配置并用 `--config` 指定。

## 运行

```bash
# CYH33，三种方法各一次
python scripts/benchmark.py run --mode smoke --run-dir results/benchmark/new-smoke

# 单个方法的 smoke test
python scripts/benchmark.py run --mode smoke --method direct --run-dir results/benchmark/direct-smoke

# 三个已暴露开发题
python scripts/benchmark.py run --mode pilot --run-dir results/benchmark/pilot

# 单个子任务 25 题，可通过 --method 缩小方法范围
python scripts/benchmark.py run --mode single-task --task target_identification --run-dir results/benchmark/target

# 单个方法的完整 75 题
python scripts/benchmark.py run --mode full --method biomdt --run-dir results/benchmark/biomdt-full

# 三种方法的全量 225 次案例级运行
python scripts/benchmark.py run --mode full --run-dir results/benchmark/comparison

# 自定义范围。--method 和 --item-id 可重复，--limit 指每种方法的案例数
python scripts/benchmark.py run --mode custom --method biomdt --item-id preclinical_research_1 --run-dir results/benchmark/custom

# 用原选择、原环境配置、原代码和原目录续跑
python scripts/benchmark.py run --mode full --run-dir results/benchmark/comparison --resume

# 重新计算现有结果，并输出高分辨率 PNG、SVG 和 PDF
python scripts/benchmark.py score --run-dir results/benchmark/new-smoke
python scripts/benchmark.py plot --run-dir results/benchmark/new-smoke --format png --format svg --format pdf
```

全量对比会执行 225 次案例级运行。每题有独立的输入、进程日志、原生方法输出和 `result.json`。续跑跳过已落盘的成功、弃答和失败结果。全量运行自动生成全 75 题和排除三个暴露案例后的 72 题汇总。重算及绘图只使用已有产物。正式论文的数值参考存于 [论文结果表](docs/published_benchmark_results.md)。


## 参考产物

仓库提供 [CYH33 开发验证汇总](results/benchmark/smoke-sol-low/tables.md) 和 [原论文结果](results/published/deepevidence_reported_results.csv)。复跑后，README 的重算和绘图命令请指向你自己的运行目录。证据核验方案及逐题审核字段见 [Benchmark 报告](docs/benchmark_summary.md)。
