# Generated projects / 生成工程

Run `wingluauqt-project --config bindings.json --root . --out build/bindings`. Paths in the policy resolve against `--root` (the policy directory by default). `project.name` and `project.namespace` default to `GeneratedBindings` and `generated_bindings`.

通过上述命令生成独立 CMake 静态库。策略中的路径相对于 `--root`，未指定时相对于策略文件；工程名及 C++ 命名空间可配置。生成目录可随时删除并重新生成，不手工修改。

## CMake and source ownership / CMake 与源码归属

Link `<Name>::Bindings` after `add_subdirectory`. In `copy` mode extension sources are copied and native MOC is run by the consuming SDK. In `reference` mode `<Name>_HOST_SOURCE_DIR` defaults to `${CMAKE_SOURCE_DIR}`; native implementations and MOC remain host-owned. `project.host_targets` must exist before adding the generated project. Native API callbacks require reference mode.

`copy` 模式复制扩展源码，由消费方 Qt SDK 运行 MOC；`reference` 模式复用宿主源码及目标，避免重复编译。生成文件不固化本机源码路径。Luau/LuaBridge3 默认位于消费方 `3rdparty/`，可覆盖 `LUAU_SOURCE_DIR` 和 `LUABRIDGE3_SOURCE_DIR`；使用与宿主匹配的依赖版本。

Include `cmake/WingLuauQt.cmake` to generate automatically at CMake configure time:

```cmake
include(3rdparty/WingLuauQt/cmake/WingLuauQt.cmake)
wingluauqt_generate(CONFIG codegen/bindings.json ROOT "${CMAKE_SOURCE_DIR}"
  OUTPUT_DIR "${CMAKE_BINARY_DIR}/generated/Bindings")
add_subdirectory("${CMAKE_BINARY_DIR}/generated/Bindings" bindings-build)
```

作为 submodule 时只包含该 CMake 模块，不必构建框架开发库。配置阶段需要 Python 3.12+ 和 tsujikiri；已导出的静态库独立编译不需要 Python。`DRIVER`、`DRIVER_CONFIG` 和 `DEPENDS` 可接入宿主自己的生成驱动及额外输入。

CMake reads the Python requirement and dependency pins from `pyproject.toml`. The stdlib-only `bootstrap.py` reuses an interpreter when all declared dependencies are available. Otherwise it automatically prepares `${CMAKE_BINARY_DIR}/.wingluauqt-venv`, using `uv` when available or Python's `venv` and `pip`. Dependency installation requires access to the configured package index. `WINGLUAUQT_PYTHON_ENV` changes the environment directory; `WINGLUAUQT_BOOTSTRAP_PYTHON=OFF` disables installation and requires a prepared `Python3_EXECUTABLE`. Only the generator dependencies are installed; exported static libraries do not need Python.

CMake 从 pyproject.toml 读取 Python 要求与依赖版本，由仅使用标准库的 bootstrap.py 检查解释器；依赖不足时自动创建构建目录下的 `.wingluauqt-venv`，优先使用 uv，否则使用 venv/pip，不修改系统 Python。可用 `WINGLUAUQT_PYTHON_ENV` 指定环境目录；离线环境应提前准备依赖并通过 `Python3_EXECUTABLE` 指定解释器，也可以关闭 `WINGLUAUQT_BOOTSTRAP_PYTHON`。首次安装需要访问配置的软件源。

The resolved policy becomes selected C++ registration statements. Exported libraries contain no policy JSON resource or runtime configuration parser. The public headers expose no registration configuration model; registration functions accept no configuration object. Change the generator inputs and regenerate to change the binding surface.

注册策略直接生成成已选定的 C++ 注册语句；交付库不包含策略 JSON 资源或运行时配置解析器。公共头文件不导出注册配置模型；注册函数不接收配置对象。调整绑定接口时修改生成输入并重新生成。

## Runtime registration / 运行时注册

Instance methods require `object:method(...)` or an explicit receiver, `object.method(object, ...)`. Missing, nil or incompatible receivers raise a catchable Luau error before native invocation. This applies to handwritten Qt adapters and generated class members.

实例方法使用 `object:method(...)`，或显式传入接收者 `object.method(object, ...)`。缺失、nil 或类型不匹配的接收者会在调用原生函数前产生可由 `pcall` 捕获的 Luau 错误；手写 Qt 适配和生成成员均遵循此规则。

`registerPublicModule`, `registerModule_<name>`, `registerModule(L, name)` and `registerAllModules(L, installRequire)` are idempotent per Lua state. The empty module key represents globals. By default the host owns execution and require: `registerAllModules(L)` uses `installRequire = false`, and `qtluau::pushModule` hands registered values to the host's module API. Clear callbacks before closing the Lua state.

默认由宿主负责脚本执行和 require；聚合注册默认不安装 require。模块值通过 pushModule 交给宿主，空模块键表示公共全局。关闭 VM 前调用 clearLuaCallbacks。对象包装通过 QPointer 检查生命周期及线程。

Optional standalone helpers are enabled at generation time:

```json
{"project": {"helpers": ["execution", "require"]}}
```

`execution` includes the execution source/header, exports `executeScript`, and links Luau.Compiler. `require` includes the standalone require wrapper and defaults `installRequire` to true. Both are omitted by default, including their public helper headers. Requesting `installRequire = true` without generating that helper throws before registration. Necessary module-value handoff remains available independently.

execution 生成执行助手及 executeScript，并链接 Luau.Compiler；require 生成独立 require 包装器，聚合注册默认安装该包装器。两者默认均不包含；示例与编辑器测试显式启用。没有生成 require 助手时请求安装会在注册前报错，模块值交接接口独立保留。

Generated CMake uses `find_package(Qt6 REQUIRED COMPONENTS ...)` without a minimum version. `qt.target_version` controls generation-time API filtering.

生成 CMake 不指定 Qt6 的最低版本；qt.target_version 仅控制生成阶段的 API 筛选。

## Shared definitions and module files / 公共定义与模块文件

```cpp
QHash<QString, QString> definitionFiles(); // shared definition: empty key
QHash<QString, QString> moduleFiles();     // named module -> physical type entry
```

Load `definitionFiles()` once through the language server's definition-file API. All shared Qt, extension and utility types occur in that file once. Each `moduleFiles()` entry is a small ordinary Luau source returning a value of the module's exported type. Register those physical paths with the host's module resolver; do not load every entry as an independent global definition file. No module is synthesized inside the language server.

公共 Qt 类型、扩展类型及模块表结构只在公共文件中定义一次。命名模块文件只引用公共类型并返回对应模块值的类型，由宿主文件解析器提供实际路径；LSP 按普通模块检查。这样不重复加载整套 Qt 声明，也不把 require 专用模块泄漏成全局变量。

Call `<Name>_copy_definitions(Executable)` after creating the executable. CMake copies both maps' files beside the executable under `luaudef`. Change `<Name>_DEFINITIONS_DIR` or `project.definitions_directory` to choose another directory. Returned runtime paths resolve against the executable directory, independently of the working directory; generated build inputs remain relative or configurable.

定义通过 CMake 复制，不放进 Qt 资源。默认部署目录为程序旁的 luaudef，可配置相对目录或外部绝对目录。运行时为真正访问文件而解析路径，不记录生成机器的固定路径。

## Application modules and callbacks / 应用模块与回调

`extra_bindings` accepts arbitrary `module`, `register`, `files` and `definitions`. The registration function belongs to `qtluau::` and stores its value with `rememberModule`. Use `framework_bindings` to select groups from the shipped `config/framework-bindings.json` contract. Python generates registration and definitions together. SDK value methods and overloads come from Qt discovery; raw VM callbacks use the contract because their C++ int(lua_State*) signature does not describe the returned Lua stack. Native C++ retains operations and lifecycle glue only.

框架通过 framework_bindings 选择分组，Python 从 Qt SDK 扫描结果及单一 VM 契约生成注册代码和定义；support/bindings 仅保留原生操作及生命周期胶水。源码与安装包使用相同生成路径。应用也可通过上述字段提供自己的实现。回调使用 `callback_sets`，函数的 `native` 字段可指定原生符号，例如 `&ScriptHost::print`；生成器同时生成定义和 `callback_initializers.inc`。该片段由宿主在允许访问原生函数的作用域中包含，避免维护第二份注册列表。

## UI creation / UI 创建

`setUiWidgetResolver` receives the class name, object name, parent and root status before default creation. Return `Default`, `Reject` or `Use` with a QWidget. The host may provide QMainWindow, QDialog, custom widgets or unknown UI roots while preserving their native type and flags.

宿主回调控制 UI 根类或任意指定类的创建；父对象所有权与 GUI 线程规则继续生效。清空回调使用 `{}`，宿主接管的根对象不会被隐式转换成其他控件。

The host supplies concrete `HostApiCallbacks` through `bindHostApi`; framework sources have no dependency on WingHex headers or plugin identities. Generated sources and definition outputs remain in the consuming build directory.

宿主通过 bindHostApi 提供具体 HostApiCallbacks；框架源码不依赖 WingHex 头文件或插件身份。生成的源码及定义产物仍位于使用方构建目录。

### Module exposure / 模块暴露

`modules.<name>.require` defaults to `false`: named modules are globals. When `true`, the module keeps its name, is hidden globally, and is listed by `moduleFiles()` for the host's builtin require registration. For example, `"modules": {"qt": {"require": true}}` exposes Qt through `require("@b/qt")` in WingHexExplorer2. Native callback rebinding preserves the same module value and exposure.

`modules.<name>.require` 默认 `false`，命名模块直接作为全局公开；设为 `true` 时名称不变，隐藏全局，并通过 `moduleFiles()` 交给宿主注册 builtin require。原生回调重新绑定保持同一个模块值及其暴露方式。

Dialog class policy can enable `implicit_parent` together with `static_only`. The SDK scan identifies `QWidget *parent` parameters by their declared name and type and generates an additional overload supplying `nullptr`, while preserving explicit-parent overloads. Native defaults remain C++ defaults. Discovered QFlags typedefs use integer conversion, so individual enum values and combined flags share the same overload.

对话框类策略可同时启用 `implicit_parent` 与 `static_only`。SDK 扫描根据声明中的名称和类型识别 `QWidget *parent` 参数，额外生成传入 `nullptr` 的重载，并保留显式父对象重载。原生默认参数由 C++ 提供。扫描获得的 QFlags 类型别名统一使用整数转换，因此单个枚举值和组合标志均可调用相同重载。
