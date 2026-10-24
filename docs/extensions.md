# Application member selection

Use the `extensions` array in a binding policy. Paths/globs are relative to the policy. Each entry supplies `headers`, optional `sources`, `include_dirs`, `defines`, `module` and a `classes` dictionary keyed by fully qualified native names. See [the complete example](../examples/bindings.json).

```json
{
  "extensions": [{
    "module": "app",
    "headers": ["../src/script_api.hpp"],
    "sources": ["../src/script_api.cpp"],
    "classes": {
      "application::Service": {
        "access": ["public"],
        "members": ["methods", "properties", "fields"],
        "constructible": true
      },
      "application::InternalService": {
        "access": ["protected", "private"],
        "non_public": "friend"
      },
      "application::Dialog": {
        "expose_base": "QWidget",
        "constructible": true
      }
    }
  }]
}
```

## Public, protected and private members

The default access selection is `public`, and default member categories are `methods`, `properties` and `fields`. `access` accepts a single visibility string or an array. Only members declared in the configured class are scanned; signals and Qt's macro-generated implementation methods are not exposed. The classes currently require QObject inheritance and Q_OBJECT. Native signatures still use the supported conversion backends rather than silently accepting arbitrary C++ types.

Public ordinary instance methods and data fields bind directly. Static members and function templates are outside this instance-wrapper backend. For restricted members, `non_public: "metaobject"` is the default: private/protected slots and invokables are invoked through Qt's public meta-object API, while ordinary private/protected methods or fields cause a generation error requesting an explicit access grant. This does not rewrite access keywords or downcast an existing object to a fake derived class.

To permit ordinary restricted members, include `<qtluau/access.hpp>` in the native declaration and grant access:

```cpp
class InternalService : public QObject {
    Q_OBJECT
    friend struct qtluau::BindingAccess<InternalService>;
private:
    int calculate(int value);
};
```

Select `non_public: "friend"` for that class. The generator specializes BindingAccess and places the actual restricted C++ accesses inside that specialization. The C++ compiler enforces the grant. Use `access` and `members` to select the surface.

## Properties and fields

Qt Q_PROPERTY is a public meta-object contract, independent of the visibility of its read/write accessors. It is selected by the public access category, uses QObject's property API, and is read-only when no write/member accessor exists. Public data fields (or explicitly friend-authorized restricted fields) use generated getters and setters. Const fields are read-only. In Luau, access them with `object.field` and `object.field = value`.

When a Q_PROPERTY and its getter share a name, the property takes precedence and the same-named method is omitted. Other method/property collisions are errors. Read-only writes are rejected by LuaBridge; declaration fields describe their value types. Container properties are detached table snapshots, so assign the changed table back through the property setter.

## Construction, base exposure and exclusions

Construction defaults to disabled, for host-created objects or constructors with application dependencies. Set `constructible` to true only for a public default constructor. Borrowed objects use QPointer and reject use after deletion and across threads; explicitly owned wrappers share a lifetime token. Widget construction requires the host QApplication and GUI thread.

`expose_base` is `QObject` (default, standalone service surface) or `QWidget`. A native QDialog subclass with QWidget exposure inherits only the QWidget wrapper API and its explicitly selected custom members, independent of the SDK's QDialog blacklist. A C++ static assertion verifies the inheritance. Native QObject pointer parameters and arbitrary custom value types need additional codecs.

Member exclusions are generation-time policy. `Class::method` removes all overloads; `Class::method(Type,Type)` removes a matching native signature. Excluding a field/property uses `Class::name`. Unsupported selected signatures fail generation with the member name. Private/protected meta-object calls support up to ten parameters; ordinary direct/friend calls have no such meta-object limit.

Moc JSON supplies Qt slots, invokables and properties. A typed libclang boundary retains ordinary member access information that tsujikiri's public IR omits. Both paths use tsujikiri's declared clang dependency and matching SDK headers; Qt SDK batch discovery itself continues to use tsujikiri IR.

## Categorized host functions

Use class rule `binding: "functions"` with member-name `include`/`exclude` patterns to export a borrowed service directly as module functions. `context` binds leading QObject pointer arguments from the host. See [generated projects](generated-projects.md) for lifecycle and source ownership. Function bindings support methods only and do not expose constructors or data properties.

## 扩展配置说明

路径相对于显式输入根目录，默认是配置文件目录。通过 headers/sources/include_dirs 选择输入，classes 维护暴露策略；默认仅 public，成员分类为 methods/properties/fields。private/protected slots 可经元对象调用，普通受限成员需 friend 授权，生成器不改写 C++ 访问权限。

Q_PROPERTY 按公开元对象契约处理；同名 getter 不重复暴露，只读属性不生成 setter。构造默认关闭，已由宿主编译的实现使用 reference 模式并关闭重复 MOC。自定义 QDialog 可以 expose_base 为 QWidget；所有对象继续遵循 QPointer 生命周期、所有权及线程检查。

函数式服务绑定可以按 include/exclude 分类，并注入前置 QObject 上下文参数。宿主的原生回调用 callback_sets 描述；native 函数指针与声明由同一配置生成，详见生成工程文档。
