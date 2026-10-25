# Version status / 版本状态

## 1.0.0

WingLuauQt generates standalone Qt/Luau static-library projects, module APIs and Luau definitions from SDK discovery and application policies. The examples and tests cover widget execution, callbacks, UI loading, application extensions and table conversions.

WingLuauQt 按 SDK 发现结果及应用策略生成独立的 Qt/Luau 静态库工程、模块接口与 Luau 定义。示例及测试覆盖控件执行、回调、UI 加载、应用扩展和 table 转换。

Python generates optional framework value bindings, module registration and Luau definitions. Qt value APIs are discovered from the SDK; signature dependencies are discovered recursively. Instance providers expose singleton APIs such as static qt.QClipboard functions without hand-maintained registration or definition files.

Python 生成可选框架值绑定、模块注册及 Luau 定义；值接口通过 SDK 发现，签名依赖递归发现；实例提供者将单例接口生成为 qt.QClipboard 等静态函数，不维护注册源码及定义文件。
