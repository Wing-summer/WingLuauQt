# Contributing to WingLuauQt / 贡献指南

Contributions use BSD-3-Clause; preserve notices belonging to dependencies. Use Python 3.12+ and a workspace virtual environment. Read [AGENTS.md](AGENTS.md) for ownership, formatting and validation rules.

贡献采用 BSD-3-Clause，保留依赖许可。使用 Python 3.12+ 和工作区虚拟环境；归属、格式及验证要求见 [AGENTS.md](AGENTS.md)。

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pyright
.venv/bin/python -m ruff check python tests/python examples/run.py
cmake -S . -B build -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build --parallel 3
ctest --test-dir build --output-on-failure
git diff --check
```

Keep application-specific inputs in that application's `codegen/`. A generator fix must update policy validation and relevant examples or documentation. Do not commit generated projects, local workspaces or downloaded tools. Describe the concrete behavior change and validation; distinguish standalone tests from a complete host build.

应用专用输入放在应用的 `codegen/`。生成器修改应同步配置校验及相关示例、文档。不提交生成工程、本机工作区或下载工具。提交说明描述实际行为和验证，区分独立测试与宿主完整构建。
