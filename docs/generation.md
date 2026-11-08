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
