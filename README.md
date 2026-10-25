# WingLuauQt

通用 Qt/Luau 绑定工程生成器：自动发现 Qt 接口，生成可独立嵌入的 CMake 静态库、模块注册函数和程序旁的 Luau 定义文件。宿主专用生成输入由宿主自己的 `codegen/` 目录维护。

Python discovers the Qt SDK, selects native APIs, and produces a **standalone CMake static-library project**. Its generated C++ exposes public and named module registration, an aggregate registration function, Luau execution, and `QHash<QString, QString>` maps of filesystem definition paths. Generated projects contain their own support sources and either snapshot native inputs or reference host-owned targets; they do not link this repository's development library.

## Run the complete example / 运行完整示例

Use Python 3.12+, CMake 3.24+, a C++17 compiler and Qt 6 Core, Gui, Widgets and UiTools. Luau and LuaBridge3 are native dependencies:

```sh
git clone https://github.com/luau-lang/luau 3rdparty/luau
git clone https://github.com/kunitoki/LuaBridge3 3rdparty/LuaBridge3
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python examples/run.py
.venv/bin/python examples/run.py --reference # reuse a host-owned service target and moc
```

The last command generates `build/example-project`, builds its static library with a separate host under `build/example-host`, and runs CTest with Qt's offscreen platform. The host executes [script.luau](examples/script.luau), exercises public/protected/private members and properties, reads definition files copied by CMake, and handles QMainWindow/QDialog/unknown UI roots through a callback.

Generate another library with:

```sh
wingluauqt-project --config application/bindings.json --out build/application-bindings
```

Execution and require helpers are omitted by default. The example explicitly enables `project.helpers: ["execution", "require"]`; embedded hosts supply these operations themselves. Module-value handoff remains available through `qtluau::pushModule`.

默认不生成执行和 require 助手；示例通过上述配置显式启用，嵌入式宿主自行提供这些操作。模块值通过 pushModule 交给宿主。

The generated project can be added with `add_subdirectory` and linked as `<project-name>::Bindings`. If moved to another machine, set its `LUAU_SOURCE_DIR` and `LUABRIDGE3_SOURCE_DIR` CMake dependency paths. CMake builds the generated project without Python or this source checkout.

Application configuration and native forwarding belong in the consuming project; see [generated projects](docs/generated-projects.md).

## Configuration and host API / 配置与宿主接口

Start with [automatic Qt Widgets and UI loading](config/application-bindings.json), which converts list/map containers directly to Luau tables without registering container aliases. See [the example policy](examples/bindings.json), [application extension configuration](docs/extensions.md), and [generated modules and definition maps](docs/generated-projects.md).

For the example, `<generated_bindings.hpp>` exports:

```cpp
example_bindings::registerPublicModule(L); // module ""
example_bindings::registerModule_qt(L);     // module "qt"
example_bindings::registerModule_app(L);    // module "app"
example_bindings::registerAllModules(L);    // idempotent aggregate
example_bindings::registerModule(L, "app");
QHash<QString, QString> definitions = example_bindings::definitionFiles();
QHash<QString, QString> modulePaths = example_bindings::moduleFiles();
QString error;
bool ok = example_bindings::executeScript(L, source, &error);
```

Member selection defaults to `access: ["public"]`. Private/protected slots and invokables use Qt's meta-object API; ordinary restricted members require an explicit `friend qtluau::BindingAccess<T>` grant and `non_public: "friend"`. Methods, Q_PROPERTY contracts and data fields are distinct selection categories. Qt properties take precedence over a getter with the same name. A custom QDialog can expose only the QWidget wrapper base.

## Source layout / 源码结构

| Directory | Responsibility |
| --- | --- |
| `python/qtluau_codegen/` | SDK discovery, access-aware member scanning, C++/Luau generation and static-project export |
| `include/qtluau/`, `support/` | Ownership, conversion, UI loading and execution support |
| `codegen/`, `build/` | Disposable generated output, excluded from version control / 可丢弃的生成产物 |
| `examples/` | Complete application generation/build/execution example |
| `config/` | Default binding policy and JSON Schema |
| `cmake/`, `tests/` | Configure-time generation orchestration and regression tests |
| `3rdparty/` | Native dependency checkouts |

## Development validation / 开发验证

```sh
cmake -S . -B build # prepares build/.wingluauqt-venv when needed
cmake --build build --parallel 3
ctest --test-dir build --output-on-failure
.venv/bin/python -m pyright
.venv/bin/python -m ruff check python tests/python examples/run.py
```

CMake reuses a compatible Python 3.12+ environment or creates `build/.wingluauqt-venv` with tsujikiri 0.32.0 (and developer checks when tests are enabled). Set `Python3_EXECUTABLE` to reuse your own environment; `WINGLUAUQT_PYTHON_ENV` selects a local environment directory and `WINGLUAUQT_BOOTSTRAP_PYTHON=OFF` requires dependencies to be installed beforehand.

CMake 优先复用依赖完整的 Python 3.12+ 环境，否则自动准备构建目录内的虚拟环境。可指定解释器、环境目录或关闭自动安装；开启测试时同时准备 Pyright/Ruff。手动创建 `.venv` 的开发方式仍然可用。

The root CMake library and `WingLuauQt::Runtime` alias provide the development harness. The delivered artifact is the independently generated static project. The Python package includes C++ support assets so installed generators can export projects too. Pylance/Pyright strict checks include the package, Python regression tests and example launcher.

## License / 许可

Framework code uses [BSD-3-Clause](LICENSE); dependencies retain their own licenses. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) for repository requirements.

框架采用 BSD-3-Clause，依赖保留各自许可。贡献及仓库维护要求见上述文档；构建产物、生成定义、本机工作区和下载依赖不纳入源码。

## API baseline, names and definition deployment / API 基准、命名与定义部署

Configure `qt.target_version` (for example `6.6.2`) and `naming.functions: "snake_case"`. Discovery respects header preprocessing and uses matching QDoc indexes to remove APIs introduced after an older target version. Class names remain unchanged. Missing version metadata is reported instead of silently claiming compatibility.

使用 `qt.target_version`（如 6.6.2）及 `naming.functions: "snake_case"` 配置 API 基准和函数命名。扫描遵循头文件预处理，对低于 SDK 的目标版本结合匹配 QDoc 索引排除较新 API；类名保持原状。缺少版本元数据会明确报错，不会静默声称兼容。

Call `<ProjectName>_copy_definitions(YourExecutable)` after creating the executable target. Definitions are ordinary files under the executable's `luaudef/` directory, configured with `<ProjectName>_DEFINITIONS_DIR` or `project.definitions_directory`. `definitionFiles()` returns the shared definition and `moduleFiles()` returns named type entry paths. See [the text editor test](tests/editor/README.md) for an interactive snake_case example with menu callbacks.

创建可执行目标后调用 `<ProjectName>_copy_definitions(YourExecutable)`，通过 CMake 将定义作为普通文件拷贝到程序旁的 luaudef。目录通过上述 CMake 变量或 `project.definitions_directory` 配置；`definitionFiles()` 返回部署后的路径映射。带菜单回调的可交互 snake_case 示例见文本编辑器测试。

## Project identity / 项目名称

WingLuauQt is the framework and CMake project name. The Python distribution is `wingluauqt`, and CLI commands use `wingluauqt-`. Python imports use `qtluau_codegen`, C++ symbols use `qtluau::`, and public headers use `qtluau/`.

框架及 CMake 工程名为 WingLuauQt，Python 分发名为 `wingluauqt`，命令采用 `wingluauqt-` 前缀。Python 导入为 qtluau_codegen，C++ 命名空间为 qtluau，公共头文件位于 qtluau/。

## CMake submodule / CMake 子模块

Include `cmake/WingLuauQt.cmake` and call `wingluauqt_generate` to create a static library during configuration. See [generated projects](docs/generated-projects.md). Host configuration and forwarding rules stay in the application's codegen directory.

作为子模块使用时包含上述 CMake 模块，无需编译框架开发库；宿主配置、生成输出路径和回调规则均由宿主 codegen 维护。语言服务器只加载一次公共定义，命名模块通过真实文件路径解析。与宿主使用相同的 Luau 版本；原生 int64 支持取决于宿主 Luau 扩展，标准 Luau 使用 number 的精确表示范围。

Optional SDK groups select root classes in `config/framework-bindings.json`; members and signature dependencies are scanned. An instance provider such as `QGuiApplication::clipboard` exposes the discovered methods as static `qt.QClipboard` functions, including image/pixmap access. No separate clipboard module is registered.

可选 SDK 分组在配置中选择根类型，成员及签名依赖由扫描获得。实例提供者将发现的剪贴板方法生成为 `qt.QClipboard` 静态接口，包括图像与像素图访问；不注册独立 clipboard 模块。
