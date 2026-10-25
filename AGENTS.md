# WingLuauQt repository guidance / 仓库协作规范

## Scope and ownership / 范围与归属

- Keep this framework generic. Application policy and concrete callback forwarding stay in the host. Select root classes and instance providers in config/framework-bindings.json. Discover members and signature dependencies through the SDK scanner; never maintain duplicate API lists. Python generates SDK bindings, module registration and Luau definitions; do not maintain copied registration sources or .d.luau files. Preserve unrelated changes and respect dependency repository boundaries.
  框架保持通用；应用策略及具体回调转发由宿主维护；在 config/framework-bindings.json 选择根类型和实例提供者，成员及签名依赖统一通过 SDK 扫描获得，不维护重复 API 清单；Python 生成 SDK 绑定、模块注册及 Luau 定义，不维护复制式注册源码或 .d.luau 文件。保留无关改动，尊重依赖仓库边界。
- Treat generated projects as disposable output. Fix generator inputs or templates and regenerate; never patch generated files. Do not add an extra project directory beneath the requested output root.
  生成工程视为可重建产物；修改输入或模板后重新生成，不手工修补生成文件，不在目标输出目录下增加项目嵌套。
- Reuse host require and language-server APIs. The empty module key means public globals. Named modules must keep their runtime ownership and definition-file maps aligned.
  复用宿主 require 与语言服务器接口；空模块键表示公共全局，命名模块的运行时归属和定义映射必须一致。

- Root `codegen/` is disposable generated output, like `build/`; keep maintained generators in `python/`, CMake orchestration in `cmake/`, and native behavior in `support/`. Do not introduce runtime registration configuration models.
  本仓库根目录 `codegen/` 与 `build/` 一样属于可丢弃产物；生成器源码放在 `python/`，CMake 调度放在 `cmake/`，原生运行行为放在 `support/`，不引入运行时注册配置模型。

## Python and C++ / Python 与 C++

- Require Python 3.12+ and Pylance/Pyright strict. Validate configuration at boundaries; use typed models, avoid `Any`, and resolve unknown dictionary values before use.
  使用 Python 3.12+ 及 strict 检查；在边界校验配置，使用明确类型，不扩散 Any，先收窄字典未知值再使用。
- Document Python modules, classes, functions and methods with English PEP 257 docstrings; describe parameters, results and relevant failures. Use `#:` comments for declared model fields. Keep code comments in English and prose documentation bilingual in one file. Preserve the requested Chinese integration guide.
  Python 模块、类、函数及方法使用英文 PEP 257 文档字符串，说明参数、结果和异常，模型字段使用 `#:` 注释。代码注释英文，说明文档同文件双语；集成指南按要求保留中文。
- Use C++17-compatible code for exported libraries. Use braces for control bodies, Qt-native interface types, explicit UTF-8 conversion, QObject parent ownership and GUI-thread checks where needed. Format owned C++ with clang-format 23.
  导出库兼容 C++17；控制语句加花括号，接口保留 Qt 类型，明确 UTF-8 转换、父对象所有权和 GUI 线程要求，使用 clang-format 23。
- Headers use `#ifndef`/`#define`/`#endif` guards. Generated guard names include the project and relative header path; detect collisions. Preserve pre-existing dependency headers and licenses.
  头文件使用宏保护，生成宏包含项目及相对路径并检测冲突；不改第三方头文件和许可。
- Keep QString as `ustring` with Luau string conversion. Ordinary Qt containers become tables; do not register List/Map aliases. Generate Luau definitions rather than LuaLS annotations.
  QString 保持 ustring 并支持 Luau string 转换；普通容器转 table，不注册 List/Map 别名；生成 Luau 定义，不使用 LuaLS 注解。

## License and repository hygiene / 许可与整理

- Framework contributions use BSD-3-Clause. Add the English copyright/SPDX notice to source and comment-capable configuration files; preserve third-party notices. Do not insert comments into JSON or empty marker files.
  框架贡献采用 BSD-3-Clause；源码及支持注释的配置添加英文版权/SPDX 头，保留第三方声明；JSON 和空标记不插入注释。
- Exclude build outputs, generated declarations, downloaded dependencies, virtual environments, caches, local editor workspaces and credentials. Keep example inputs and templates visible. Keep release versions and CHANGELOG consistent.
  排除构建和生成产物、下载依赖、虚拟环境、缓存、本机编辑器工作区及凭据；示例输入和模板保持可见，版本与 CHANGELOG 一致。
- Use workspace-local tools and dependencies. Do not install system packages automatically or hard-code checkout paths in maintained source.
  工具及依赖放在工作区，不自动安装系统包，不在维护源码中硬编码本机路径。

## Validation / 验证

```sh
.venv/bin/python -m pyright
.venv/bin/python -m ruff check python tests/python examples/run.py
cmake -S . -B build -DPython3_EXECUTABLE="$PWD/.venv/bin/python"
cmake --build build --parallel 3
ctest --test-dir build --output-on-failure
git diff --check
```

- Validate installed package assets and independently generated CMake projects when export changes. Test definitions against the target Luau version. Distinguish syntax checks, isolated execution tests and full host builds; report environmental limitations precisely.
  导出逻辑变更时检查安装包资源及独立生成工程；使用目标 Luau 检查定义，区分语法、独立执行和宿主完整构建，如实说明环境限制。
