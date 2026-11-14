# Discovery and configuration / 发现与配置

Policies contain API selection and conversion rules, not hand-entered Qt header paths. SDK discovery uses pkg-config, qtpaths or qmake and tsujikiri. Source SDK paths appear only in disposable scan diagnostics, not exported project inputs.

策略配置见 `config/bindings.schema.json`，以 `config/application-bindings.json` 为自动发现示例。扫描通过 pkg-config、qtpaths 或 qmake 发现 SDK，再调用 tsujikiri。SDK 路径仅用于本次扫描，维护的策略不填写每个 Qt 头文件的位置。

```sh
wingluauqt-discover --config config/application-bindings.json --out build/discovery
wingluauqt-project --config examples/bindings.json --out build/example-project
```

## Qt selection / Qt 选择

- `qt.discovery.modules`: Qt modules to scan / 扫描的 Qt 模块。
- `qt.discovery.bases`: inheritance roots, including indirect descendants / 基类及其间接派生类。
- `qt.discovery.blacklist`: class-name patterns, applied before dependency closure / 依赖闭包前的类名排除模式。
- `qt.discovery.dependencies`: transitive supported signature dependencies / 递归收集受支持签名的依赖。
- `qt.widgets.include` and `extra_types`: explicit additions such as layouts / 补充布局等类型，不用于枚举所有按钮。
- `exclude.classes` and `exclude.members`: class and member restrictions / 类及成员排除。

Ordinary containers are converted to tables and must not be selected as wrapper classes. Unsupported signatures are reported; unknown native values are not represented as `any` to conceal missing codecs. Handwritten lifetime/Qt adapters and discovered public methods share the same selected surface.

普通容器转为 Luau table，不选择 QStringList 等包装类。未知原生类型和不受支持的签名在扫描报告中说明；新增转换器时同步实现运行时转换及定义生成。C++ 风格迭代器不导出。

## API baseline and names / API 基准与名称

Set `qt.target_version`, for example `6.6.2`. Header preprocessing determines actual available declarations. When scanning a newer SDK for an older baseline, matching QDoc indexes supply API introduction versions; missing metadata is an error. This filtering does not replace compilation with the baseline SDK.

头文件预处理决定真实可见的声明；较新 SDK 向旧基准生成时，还需要匹配 SDK 的 QDoc 索引识别 API 引入版本。验证时应区分 API 筛选和真正使用基准 SDK 编译。

`naming.functions` defaults to `snake_case`; `native` is an explicit compatibility option. Native C++ names remain unchanged; registration keys and Luau definitions use the same transformation. Class names are preserved.

默认使用 snake_case，方法注册名及定义同步变化，例如 `setWindowTitle` 变为 `set_window_title`，Qt 类名不变。

## Common types and outputs / 公共类型与产物

Configure aliases and methods through `common.types`. See [types and containers](types-and-containers.md) and [application extensions](extensions.md).

统一通过 common.types 配置类型别名、启用状态及方法。受限成员使用 access、members 和 non_public。

Scan outputs include resolved policy, discovery reports, translation units and temporary tsujikiri input. Exported projects retain only compilation inputs, compiled registration statements and compact Luau type files. Load the shared definition once and resolve named type entries as ordinary modules; see [generated projects](generated-projects.md).

扫描目录是可删除中间产物，导出工程只保留编译所需内容。公共定义与各模块类型入口分离，仅加载公共定义和对应的模块类型入口。

## Configure reuse / 配置阶段复用

CMake checks the contents of generation inputs and published outputs before scanning. An unchanged configure reuses the complete project without starting SDK discovery. Policy/driver changes, transitive local headers, framework sources, SDK headers, tool/environment changes and missing or modified generated files invalidate reuse. Touching an unchanged input or editing an unrelated host file does not regenerate bindings. Checkpoints and configure locks live beside the generated directory in the build tree; failed generation never updates the checkpoint. Configure calls sharing one output are serialized.

CMake 在扫描前校验生成输入及已发布产物的内容。无改动时直接复用完整工程，不启动 SDK 扫描。策略或宿主驱动、间接引用的本地头文件、框架源码、SDK 头文件、工具／环境以及生成文件缺失或内容变化都会使复用失效；仅更新时间戳或编辑无关宿主文件不会重建绑定。校验记录及配置锁放在构建树的生成目录旁，生成失败不更新记录；共享输出目录的配置调用会串行执行。

Use `-DWINGLUAUQT_FORCE_GENERATION=ON` to force a scan, then switch it back to `OFF` for normal reuse. The first configure and input-changing configures still perform full discovery. Standalone framework configuration emits runtime bindings and definitions in one Python process, avoiding a second SDK initialization. The CLI exposes the same combined operation through `qtluau_codegen.qt_pipeline --definitions-out <directory>`.

需要强制扫描时使用 `-DWINGLUAUQT_FORCE_GENERATION=ON`，随后改回 `OFF` 恢复正常复用。首次配置及输入变化后的配置仍执行完整扫描。框架独立配置在同一 Python 进程中生成运行时绑定与类型定义，避免第二次 SDK 初始化；命令行也可通过 `qtluau_codegen.qt_pipeline --definitions-out <directory>` 执行合并生成。

## Scan performance / 扫描性能

SDK catalogs initialize when generation needs them, rather than during module
imports or CLI help. The main process extracts global declarations while one
spawned worker inventories SDK-owned namespaces and extracts their declarations.
Parsing uses tsujikiri's `SourceConfig`, `ParseKey`, `parse_worker` and
`merge_modules`; signals and public using declarations come directly from its
IR. The supplemental pass retains only compiler facts absent from that IR:
canonical aliases, macro-deleted constructors and namespace ownership.

SDK 目录在生成时按需初始化，导入模块和查看命令行帮助不会启动扫描。主进程
提取全局声明，同时一个通过 spawn 启动的工作进程发现 SDK 所属命名空间并
提取其声明。解析复用 tsujikiri 的 `SourceConfig`、`ParseKey`、`parse_worker`
和 `merge_modules`，信号与公开 using 声明直接取自 IR。补充扫描仅保留该 IR
尚未提供的编译器信息：规范化别名、通过宏删除的构造函数及命名空间归属。

Canonical namespace declarations distinguish SDK-owned scopes from namespaces
reopened by SDK headers, avoiding a standard-library blacklist. The pinned
0.33.0 dependency has no public scope-inventory API; one typed compatibility
boundary reuses its `_iter_scope_decls` traversal so nested and inline namespace
semantics remain identical to its parser. No parser monkey-patching or copied
extraction implementation is used. Native API parser scopes are derived from
configured qualified symbols rather than a maintained namespace allowlist.

使用命名空间的规范声明判断其是否属于 SDK，避免把 SDK 头文件重新打开的
标准库命名空间误认为 SDK 本身，不维护标准库黑名单。当前固定依赖 0.33.0
没有公开的命名空间清点接口，因此通过一个带类型约束的兼容边界复用其
`_iter_scope_decls` 遍历，保持嵌套与 inline 命名空间的处理语义一致；不修改
解析器运行时行为，也不复制声明提取实现。宿主 API 的解析范围由配置中的完整
符号名推导，不维护命名空间白名单。

Native interfaces are prefetched concurrently with Qt generation through
`ParseCache(jobs=2).prefetch()` and consumed in configuration order. Repeated
extension headers with identical compiler flags share one member scan within
an export. SDK catalogs reuse the active module snapshot instead of first
scanning the default component set. Member exclusion policies are compiled
into literal indexes and wildcard regular expressions; signature normalization
runs once per pattern snapshot, rather than once per pattern and candidate.

宿主接口通过 tsujikiri 的 `ParseCache(jobs=2).prefetch()` 与 Qt 生成并行执行，
结果按配置顺序使用。同次导出中，编译参数相同的重复扩展头文件复用成员扫描。
SDK 目录直接使用当前模块集合的扫描结果，不再先扫描一遍默认组件。
成员排除规则预编译为精确查询集合和通配符正则表达式；规则签名在配置快照编译时
规范化一次，避免为每个候选成员重新规范化整组规则。

All parses skip function bodies and reject compiler errors. Results are merged,
diagnostics replayed and files emitted by the caller in a stable order. No new
configuration is required. SDK scanning can retain two Clang translation units;
native prefetch adds up to two more workers. Per-export IR and member caches
are released with the export. CMake's complete-output cache still handles
unchanged configures; measure full generation, SDK scanning and cache hits
separately.

所有扫描跳过函数体，并检查编译错误；结果合并、诊断输出及文件生成仍由调用
线程按稳定顺序完成。不需要新增配置；SDK 扫描可同时驻留两个 Clang 翻译单元，
宿主预取最多增加两个工作进程。同次导出使用的 IR 和成员缓存随导出结束释放。
CMake 的完整产物缓存继续处理未变动的配置；应分别测量完整工程生成、SDK 扫描
及命中缓存的耗时。
