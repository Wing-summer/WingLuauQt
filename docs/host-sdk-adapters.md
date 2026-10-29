# Host SDK adapters / 宿主 SDK 适配

The partial overlay in `examples/host-sdk-adapters.json` selects module roots without a framework-owned module implementation. Merge it into a host configuration, remove conflicting class exclusions, and provide the referenced native header and implementation in the host. It is not a standalone permission policy.

`examples/host-sdk-adapters.json` 是局部配置示例，选择模块根类型而不在框架中维护模块实现。使用时合并进宿主配置，移除冲突的类排除项，并由宿主提供引用的原生头文件和实现。示例本身不是完整权限策略。

`sdk_bindings.modules` maps module/member names to SDK classes. A class adapter may specify `includes`, a QObject `factory`, a `guard` invoked before generated native calls, and instance `methods` redirected to native adapters. Factories receive the scanned constructor arguments. Guards receive the native receiver (null for static calls). An optional `guard_selector` selects an entry in `sdk_bindings.guard_selectors`: `const`/`mutable` defaults and ordered native-method glob `rules` choose a C++ token at generation time. This token is passed before the receiver, allowing a host enum check without runtime string dispatch. Redirected methods receive the native receiver followed by scanned arguments. `inherited_methods` includes public base APIs while respecting C++ name hiding. API signatures, overloads, conversions, definitions and indexes still come from the SDK scanner.

`sdk_bindings.modules` 将模块及成员名映射到 SDK 类。类适配可指定 `includes`、QObject `factory`、原生调用前执行的 `guard`，以及转发给原生适配的实例 `methods`。工厂接收扫描出的构造参数。检查函数接收原生 receiver，静态调用时为空；可选的 `guard_selector` 引用 `sdk_bindings.guard_selectors`，由 `const`/`mutable` 默认值及按序匹配原生方法名的 glob `rules` 在生成时选择 C++ 标记，放在 receiver 前传入，因此宿主可用枚举检查，无需运行时字符串分派；方法适配接收原生 receiver 及扫描参数。`inherited_methods` 扫描公共基类接口并遵守 C++ 名称隐藏规则。API 签名、重载、转换、定义及索引仍由 SDK 扫描产生。

`sdk_bindings.type_annotations.<native type>` may override `argument` and `result` annotations to match a host VM's scalar representation. This changes declarations only; the configured contract must match the native codec.

`sdk_bindings.type_annotations.<原生类型>` 可覆盖 `argument`、`result` 类型声明，以匹配宿主 VM 的标量表示。这仅改变定义，配置契约必须与原生转换一致。

## Signals and context lifetimes / 信号与上下文生命周期

The scanner preserves Qt signal annotations. SDK QObject bindings generate typed queued signal connectors and callback declarations; signal methods are not ordinary callable members. Value arguments are copied, QObject pointers use QPointer, and unsupported temporary-pointer signals are reported. Native signal names, full signatures and snake_case aliases are accepted by the existing `connect` method.

扫描器保留 Qt 信号标记。SDK QObject 绑定生成带类型的排队信号连接及回调声明，不将信号作为普通方法公开；值参数复制，QObject 指针使用 QPointer，无法安全保存的临时指针信号进入报告。既有 connect 接口接受原生信号名、完整签名及 snake_case 别名。

Set a class adapter's `context_owned` to track newly constructed QObjects through the generic lifetime hooks. The host installs `setLuaContextResolver` per VM to associate coroutine states with an execution context and calls `clearLuaContext` before resetting that context. `clearLuaCallbacks` disposes all remaining VM resources before lua_close. Borrowed return objects are not adopted. A `constructible: false` adapter publishes a type without constructors. `return_types` can refine a method's QObject pointer result to a discovered derived class; the generator validates ancestry and emits qobject_cast.

类适配的 context_owned 将新构造 QObject 关联到通用生命周期钩子。宿主为每个 VM 安装上下文解析器，并在重置上下文前清理；关闭 VM 前清理剩余资源。借用返回值不被接管。constructible 可禁止构造；return_types 可将方法返回的 QObject 指针细化为扫描得到的派生类型，生成器验证继承关系并生成 qobject_cast。

`module_dependencies.<module>.sdk_modules` additionally exports discovered dependency classes from those SDK components using snake_case aliases after removing `Q`. Existing explicit aliases take precedence, and collisions fail generation. `enum_namespaces` selects scanned namespace enums with a destination module and alias. Component headers and linked Qt targets follow the configured SDK modules. See `examples/network-sdk.json` for a standalone example; hosts own their concrete module policy.

module_dependencies 可将指定 SDK 组件中的依赖类自动导出为简短别名；显式别名优先，冲突报错。enum_namespaces 选择扫描得到的命名空间枚举及目标模块、别名。Qt 头文件和链接目标跟随 SDK 模块配置。具体模块策略由宿主维护。
