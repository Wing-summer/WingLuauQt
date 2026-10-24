# 类型策略、QVariant 与容器

## 统一的类型注册表

配置使用 Qt 类型名作键。别名、启用状态和方法允许列表使用同一结构：

```json
{
  "common": {
    "types": {
      "QString": {"alias": "ustring", "enabled": true, "methods": ["*"]},
      "QByteArray": {"alias": "bytearray"},
      "QVariant": {"alias": "variant"},
      "QColor": {"alias": "color"},
      "QSpinBox": {"alias": "spinner"}
    }
  }
}
```

已具备后端的 Qt 类型可直接配置全局别名；例如 `color == qt.QColor`、`spinner == qt.QSpinBox`。给已有类型添加别名无需增加 C++ 配置字段。未知、未编译的类型会报错，不能仅通过一个名称创建出尚未实现的绑定。

QString、QByteArray、QVariant 的适配器有默认策略；其他显式配置的 Qt 类型通过已注册的 `qt` 类表发布别名。通过 common.types 配置。

`enabled: false` 隐藏该类型的构造入口。`methods` 控制 userdata 的实例方法，支持 `['*']` 或指定名称，成员排除规则优先。列表和映射容器不参与此别名注册表，也不提供包装构造入口；它们直接转换为 Luau table，使用 table 库操作。构造器排除仍使用 `exclude.members`。

## QString、ustring 与 Luau string

QString 继续注册为 `ustring`，其 userdata 接口保持不变，且 `qt.QString == ustring`。列表、映射容器不注册别名的规则不影响 QString。

```lua
local source = "你好😀"
local text = ustring(source)          -- Luau string 按 UTF-8 解码为 QString
local result: string = text:to_utf8()  -- QString 编码为 UTF-8 Luau string
assert(result == source)
local copy = ustring(text)            -- 复制已有 ustring
```

有效 UTF-8 文本中的内嵌零字符也能保留。QString/ustring 的长度按 UTF-16 代码单元计算，Luau string 的 `#` 按字节计算，两者长度不必相同。任意二进制数据使用 QByteArray/bytearray。

现有字符串返回接口继续按其已生成的签名返回；需要 `ustring` 时显式调用构造函数，需要 Luau string 时调用 `to_utf8()`。这不会自动为 ustring 增加 Luau string 库的全部操作。

## 容器与迭代

不配置 `stringlist`、`variantlist`、`variantmap` 或其他容器别名，也不构造 `qt.QStringList()`、`qt.QVariantList()`、`qt.QVariantMap()`。在 `common.types` 配置容器或将其作为 Qt 类选中会报错；转换层仍接受对应原生签名。

QStringList、QVariantList、QList/Qt6 QVector 转为从 **1** 开始的连续 table；QVariantMap、QVariantHash、QMap<QString, T>、QHash<QString, T> 转为字符串键 table。泛型容器递归转换元素，支持数值、bool、QString、QByteArray、已注册的 QColor/QFont 值类型和已支持的嵌套容器。生成器只接受元素本身具有转换支持的容器签名。

```lua
local names = {"张三", "李四"}
table.insert(names, "王五")
for index, name in names do
    print(index, name)
end
-- ipairs(names)、pairs(names) 同样可用。

local combo = qt.QComboBox()
combo:add_items(names)
combo:set_item_data(0, {id = 123, tags = {"a", "b"}}, 256)
local data = combo:item_data(0, 256)
assert(data.tags[2] == "b")
```

C++ 的 begin/end、cbegin/cend、反向迭代器和 iterator 签名不导出。容器是独立快照：修改返回的 table 不会隐式修改 Qt 对象；通过 setter 或方法参数显式写回。table 的元表、对象身份与共享子表身份不跨边界保留。

输入序列必须连续且没有空洞；映射必须只有字符串键。混合数字/字符串键、其他键类型、循环 table、函数、线程和未支持的 userdata 会报错。一次转换最多递归 64 层、100000 个值。支持原生 int64 的宿主 Luau 保留有符号 64 位整数；更大的 uint64 保持 QVariant 包装。标准 Luau 对无法精确表示的整数拒绝拆箱。

## QVariant：自动拆装箱与显式保留类型

此前只有 property 的零散标量转换，没有统一 QVariant 接口。现在自动生成的方法、`property/setProperty`、容器与显式 QVariant 共享同一转换层。

默认映射：

| Qt 值 | Luau 值 |
| --- | --- |
| 无效 QVariant | nil |
| bool / 可精确表示的整数 / 浮点数 | boolean / number |
| QString / QByteArray | UTF-8 string / 二进制 string |
| QStringList / QVariantList | 序列 table |
| QVariantMap / QVariantHash | 字符串键 table |
| QColor / QFont | 已注册的 Qt 值 userdata |
| nullptr 或容器内的无效 QVariant | `qt.null` 哨兵 |

Luau table 不能保留 nil 元素，因此 `qt.null` 表示容器中的显式空值；它不是 nil，迭代不会因此中断。顶层 nil 转为无效 QVariant。

普通 Lua number 默认装为 double，普通 string 默认装为 QString，空 table 默认装为 QVariantList。需要精确 Qt 类型（包括空映射、整数类型、二进制内容）时显式装箱：

```lua
local box = qt.QVariant({answer = 42}, "QVariantMap")
assert(box:type_name() == "QVariantMap")
local copy = box:to_value()
assert(copy.answer == 42)

local emptyMap = variant({}, "QVariantMap")
local bytes = variant(bytearray("a\0\255"))
local exact = variant("9223372036854775807", "qlonglong")
-- 原生 int64 Luau 可精确拆箱；标准 Luau 超出 number 精度范围时拒绝拆箱。
```

QVariant 包装提供 `is_valid()`、`is_null()`、`type_name()`、`to_value()`，不暴露任意 Qt 类型转换、裸指针或 QObject*。目前支持显式请求 bool、int、uint、qlonglong、qulonglong、double、QString、QByteArray、QStringList、QVariantList、QVariantMap、QColor、QFont。未知 metatype 会报错，新增 Qt 值类型需同时增加绑定和 QVariant 转换后端。

`setProperty` 先通过此转换层，再按已声明 Qt 属性类型转换；只读属性拒绝写入。动态属性支持 table 与嵌套值，nil 删除属性。Qt 原生 setter 对动态属性即使成功也返回 false，这里按实际存储结果报告成功。

新声明仍使用 Luau extern type 语法；容器声明为 `{T}` / `{[string]: T}`。QVariant 是动态类型，自动拆箱结果声明为 `any`，显式包装的元信息方法有确定类型。

## Type policy summary

Use canonical Qt type names under `common.types` for aliases, enabled state and method selection. QString remains `ustring` with explicit UTF-8 conversion. Ordinary lists and maps convert to detached Luau tables; C++ iterators and container aliases are not exposed. Naming follows the configured native or snake_case policy.

QVariant preserves explicit native types when boxed. Null elements use the shared sentinel. Containers reject cycles, unsupported keys and unsupported userdata, and have depth/value limits. Integer behavior depends on the host Luau: native int64 preserves signed 64-bit values and larger unsigned values stay boxed; standard Luau rejects values outside exact number precision.
