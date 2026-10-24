# Architecture / 架构

WingLuauQt is an unreleased Qt/Luau static-library project generator. Python resolves application policy against a Qt SDK; the exported C++ project compiles independently of Python. Public headers use `qtluau/` and symbols use `qtluau::`.

WingLuauQt 是未发布的 Qt/Luau 静态库工程生成器。Python 根据 Qt SDK 解析应用策略，导出的 C++ 工程独立于 Python 编译。公共头文件位于 qtluau/，命名空间为 qtluau。

## Discovery and generation / 发现与生成

- `discovery.py`, `selection.py`, `api_baseline.py`: SDK discovery through tsujikiri 0.32.0, inheritance selection, exclusions, dependencies and API version filtering.
- `member_scan.py`, `class_codegen.py`, `extensions.py`: QObject extensions, visibility, properties, friend access and exposed bases.
- `registration_codegen.py`: concrete registration statements selected at generation time.
- `qt_pipeline.py`: native method bindings, default argument overloads and typed child lookup generated from SDK discovery. Generic templates carry native widget and layout references.
- `native_values.py`: SDK-derived value methods registered against the generic `QtValueRef<T>` storage template. Native string decoding and UTF-8 conversion remain boundary functions.
- `type_mapping.py`, `type_policy.py`, `generate_definitions.py`, `module_definitions.py`: conversion policies and shared Luau declarations with small module entry files.
- `project.py`: standalone CMake export, source ownership and definition deployment.

上述模块分别负责 SDK 发现及版本筛选、应用成员扫描、静态注册、原生方法绑定、类型定义和工程导出。QtValueRef<T> 仅保存原生值，值类型方法由 native_values.py 从 SDK 生成；字符串解码和 UTF-8 转换属于边界函数。根目录 codegen/ 与 build/ 是可删除产物；宿主自己的 codegen/ 保存应用输入。所有选择与排除在生成阶段完成。

## Adapter contract / 适配契约

`catalog.py` derives the binding surface from C++ support declarations and tsujikiri's active SDK records. Wrapper signatures, string overloads, child lookup types, native constructors and supported value methods are computed during generation. Ordinary widget methods retain the native SDK names and signatures; no separate convenience-operation table is maintained.

catalog.py 在生成时根据 C++ 支持声明和 tsujikiri 的 SDK 记录计算绑定接口，包括 wrapper 签名、字符串重载、子控件类型、原生构造函数及受支持的值类型方法。普通控件方法采用 SDK 原生名称与签名，不维护独立的便利操作清单。

`config/bindings.json` supplies default aliases and safety policy. It is shipped with the C++ support assets. The Python package does not maintain a separate adapter API database. Generation requires a usable Qt SDK, including when only declarations are requested. SDK scan results are reused within one generator process.

config/bindings.json 提供默认别名与安全策略，随 C++ 支持文件分发。Python 包不维护另一份适配 API 数据库；仅生成定义时也需要可用的 Qt SDK。同一生成进程复用扫描结果。

`wrapper_contract.py` accepts the maintained support declaration grammar and rejects unsupported types. Application C++ uses the native scanners. `qt_pipeline.py` emits native registration lambdas; explicit support implementations own lifetime and custom semantics. Native compilation validates generated calls against the SDK.

wrapper_contract.py 读取维护的支持声明并拒绝未知类型，应用 C++ 使用原生扫描器。qt_pipeline.py 生成原生方法注册 lambda；显式 support 实现维护生命周期和特殊语义。原生编译验证生成调用与 SDK 一致。

## Runtime and host boundary / 运行支持与宿主边界

`support/` implements QObject lifetime, GUI-thread checks, Lua callback lifetime, QVariant/table conversion, UI file validation and optional execution helpers. `ui_codegen.py` generates the QUiLoader backend and allowed classes from SDK discovery and application policy. Application implementations and module registration belong to the consuming project. See [extensions](extensions.md), [types](types-and-containers.md) and [generated projects](generated-projects.md).

support/ 维护对象生命周期、GUI 线程检查、回调存活、QVariant/table 转换、UI 文件校验及可选执行辅助。ui_codegen.py 根据 SDK 发现结果与应用策略生成 QUiLoader 后端和允许的类。应用实现与模块注册由宿主维护。公共定义加载一次，命名模块的物理类型入口由宿主解析器提供；语言服务器通过其定义文件接口加载类型。

## Validation / 验证

CTest exercises generated registration, receiver errors, exclusions, definitions, extensions, conversions, UI loading and independent project export. Python uses Pyright strict and Ruff. The example host and menu-based editor test execute Luau against the generated library.

CTest 覆盖生成注册、接收者错误、排除规则、定义、扩展、转换、UI 加载及独立工程导出。Python 使用 Pyright strict 和 Ruff；示例宿主及带菜单的编辑器测试执行生成库中的 Luau 代码。

## Signals / 信号

Widgets and borrowed QObject values expose `connect(signal, callback)`. Use a Qt signal name or its full signature for overloaded signals, for example `button:connect("clicked", function() end)`. The current bridge invokes callbacks without signal arguments. QObject references check deletion and thread affinity; callbacks are released before the Luau state closes.

控件与借用的 QObject 值提供 connect(signal, callback)。使用 Qt 信号名称，重载信号则使用完整签名，例如 button:connect("clicked", function() end)。当前桥接调用回调时不传信号参数；对象引用检查删除状态及线程，回调在 Luau 状态关闭前释放。
