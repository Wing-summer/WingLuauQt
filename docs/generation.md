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
