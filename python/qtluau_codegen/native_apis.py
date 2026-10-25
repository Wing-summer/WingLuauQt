# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate SDK value types and typed host callback contracts from tsujikiri IR.

Unlike QObject extensions, this path supports ordinary C++ SDK interfaces and
structs. Group namespaces and require module ownership are independent.
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import pathlib

from .catalog import NATIVE_CLASSES
from .discovery import discover_sdk
from .extensions import identifier, paths, write
from .models import JsonObject, object_field, object_list_field, string_list_field
from .module_policy import requires_module
from .type_mapping import mapped_type


def emit_native_apis(config: JsonObject, out: pathlib.Path, base: pathlib.Path) -> list[JsonObject]:
    """Scan application native APIs and emit typed callback contracts and definitions."""
    from tsujikiri.configurations import SourceConfig
    from tsujikiri.ir import IRFunction, IRMethod
    from tsujikiri.parser import parse_translation_unit_ir

    entries = object_list_field(config, "native_apis")
    metadata: list[JsonObject] = []
    declarations = ["#pragma once", '#include "qtluau/packages.hpp"', "#include <functional>"]
    generated: set[str] = set()
    for index, entry in enumerate(entries):
        headers = paths(base, string_list_field(entry, "headers"))
        include_dirs = paths(base, string_list_field(entry, "include_dirs"))
        flags = [
            "-std=c++20",
            *discover_sdk(["QtCore", "QtGui", "QtWidgets"]),
            *["-I" + str(d) for d in include_dirs],
        ]
        scan = out / f"native_scan_{index}.hpp"
        scan.write_text("\n".join(f'#include "{p}"' for p in headers))
        errors: list[str] = []
        ir = parse_translation_unit_ir(
            SourceConfig(path=str(scan), parse_args=flags), [], "native", clang_errors=errors
        )
        if errors:
            raise ValueError("Cannot scan native APIs:\n" + "\n".join(errors))
        classes = {c.qualified_name: c for c in ir.classes}
        types = object_field(entry, "types")
        aliases = {
            native: f"_ext_{rule['namespace']}_{rule['name']}" for native, rule in types.items()
        }

        def qualified(spelling: str) -> str:
            """Qualify native enum and value names for generated C++ source."""
            for native in [*types, *object_field(entry, "enum_types")]:
                if spelling == native.rsplit("::", 1)[-1]:
                    return native
            return spelling

        def qualified_default(value: str) -> str:
            """Qualify scoped enum defaults using the configured native type names."""
            compact = "".join(value.split())
            for native in object_field(entry, "enum_types"):
                short = native.rsplit("::", 1)[-1]
                if compact.startswith(short + "::"):
                    return native.removesuffix(short) + value
            return value

        def conversion(spelling: str, result: bool = False) -> tuple[str, str, str]:
            """Build the native-to-Luau conversion expression for a supported type."""
            bare = qualified(spelling.removeprefix("const ").replace("&", "").strip())
            if bare in types:
                return (
                    ("luabridge::LuaRef" if result else f"QtArgument<{bare}>"),
                    aliases[bare],
                    "qtToLua(L, {expr})" if result else "{expr}.value",
                )
            if bare in object_field(entry, "enum_types"):
                return (
                    ("luabridge::LuaRef" if result else f"QtArgument<{bare}>"),
                    "number",
                    "qtToLua(L, {expr})" if result else "{expr}.value",
                )
            if bare == "QUrl":
                return (
                    ("luabridge::LuaRef" if result else "QtArgument<QUrl>"),
                    "_qt_QUrl",
                    "qtToLua(L, {expr})" if result else "{expr}.value",
                )
            mapped = mapped_type(spelling, result)
            if (
                mapped is None
                and bare in NATIVE_CLASSES
                and NATIVE_CLASSES[bare].get("copyable", True)
            ):
                required = set(string_list_field(config, "_sdk_required_types"))
                required.add(bare)
                config["_sdk_required_types"] = sorted(required)
                return (
                    "luabridge::LuaRef" if result else f"QtArgument<{bare}>",
                    "_qt_" + bare,
                    "qtToLua(L, {expr})" if result else "{expr}.value",
                )
            if mapped is None:
                raise ValueError(f"Unsupported native API type: {spelling}")
            lua_type = mapped[1]
            if bare in {"qint64", "qlonglong", "qsizetype", "qintptr", "long long"}:
                lua_type = str(entry.get("integer_type", "number"))
            elif bare in {"quint64", "qulonglong", "quintptr", "unsigned long long"}:
                lua_type = str(entry.get("unsigned_integer_type", "number"))
            elif not result and bare == "QString":
                lua_type = "string | ustring"
            elif not result and bare == "QByteArray":
                lua_type = "string | bytearray"
            if not result and lua_type.startswith("integer"):
                lua_type += " | number"
            mapped = mapped[0], lua_type, mapped[2]
            return mapped

        public_headers = [p.relative_to(base.resolve()).as_posix() for p in headers]
        includes = [
            '#include "qtluau/packages.hpp"',
            "#include <QPointer>",
            "#include <QMetaEnum>",
            "#include <QThread>",
            "#include <QCoreApplication>",
            "#include <tuple>",
            *[f'#include "{p}"' for p in public_headers],
        ]
        declarations.extend(f'#include "{p}"' for p in public_headers)
        for native in types:
            rule = object_field(types, native)
            namespace = identifier(rule["namespace"])
            name = identifier(rule["name"])
            symbol = f"register_native_{index}_{namespace}_{name}"
            record = classes.get(native)
            if record is None:
                raise ValueError(f"Native type not found: {native}")
            code = [
                *includes,
                "namespace qtluau {",
                f"void {symbol}(lua_State *L) {{",
                f'auto cls = luabridge::getGlobalNamespace(L).beginNamespace("{namespace}").beginClass<{native}>("{name}");',
                "cls.addConstructor<void (*)(), void (*)()>();",
            ]
            properties: list[JsonObject] = []
            for field in record.fields:
                if field.is_static:
                    continue
                arg, lua, _ = conversion(field.type_spelling)
                read = conversion(field.type_spelling)[2].format(expr="value")
                result = conversion(field.type_spelling, True)[2].format(expr=f"self.{field.name}")
                state = ", lua_State *L" if "qtToLua" in result else ""
                code.append(
                    f'cls.addProperty("{field.name}", [](const {native} &self{state}) {{ return {result}; }}, []({native} &self, {arg} value) {{ self.{field.name} = {read}; }});'
                )
                properties.append({"name": field.name, "type": lua, "readonly": False})
            methods: list[JsonObject] = []
            for method in record.methods:
                if (
                    method.access != "public"
                    or method.is_static
                    or method.parameters
                    or method.name.startswith("operator")
                ):
                    continue
                result = conversion(method.return_type, True)
                code.append(
                    f'cls.addFunction("{method.name}", [](const {native} &self, lua_State *L) {{ return {result[2].format(expr="self." + method.name + "()")}; }});'
                )
                methods.append({"name": method.name, "parameters": [], "result": result[1]})
            code.extend(["qtluau::guardClassMethods(L, cls); cls.endClass();", "}", "}"])
            filename = f"native_{index}_{namespace}_{name}.cpp"
            write(out / filename, "\n".join(code) + "\n")
            generated.add(filename)
            declarations.append(f"namespace qtluau {{ void {symbol}(lua_State *L); }}")
            metadata.append(
                {
                    "module": "",
                    "namespace": namespace,
                    "name": name,
                    "native": native,
                    "base": "",
                    "constructible": True,
                    "methods": methods,
                    "properties": properties,
                    "register": symbol,
                }
            )
        for native in object_field(entry, "enum_types"):
            rule = object_field(object_field(entry, "enum_types"), native)
            namespace, name = identifier(rule["namespace"]), identifier(rule["name"])
            symbol = f"register_native_{index}_{namespace}_{name}"
            enum = next((e for e in ir.enums if e.qualified_name == native), None)
            if enum is None:
                raise ValueError(f"Native enum not found: {native}")
            values = {v.name: v.value for v in enum.values}
            code = [
                *includes,
                "namespace qtluau {",
                f"void {symbol}(lua_State *L) {{",
                f'auto table = luabridge::getGlobalNamespace(L).beginNamespace("{namespace}").beginNamespace("{name}");',
            ]
            code.extend(
                f'table.addVariable("{key}", static_cast<int>({native}::{key}));' for key in values
            )
            code.extend(["}", "}"])
            filename = f"native_{index}_{namespace}_{name}.cpp"
            write(out / filename, "\n".join(code) + "\n")
            generated.add(filename)
            declarations.append(f"namespace qtluau {{ void {symbol}(lua_State *L); }}")
            metadata.append(
                {
                    "module": "",
                    "namespace": namespace,
                    "name": name,
                    "native": native,
                    "base": "",
                    "binding": "enum",
                    "values": values,
                    "methods": [],
                    "properties": [],
                    "register": symbol,
                }
            )
        selected = string_list_field(entry, "classes")
        available: list[IRMethod | IRFunction] = [
            m
            for cls in ir.classes
            if cls.qualified_name in selected
            for m in cls.methods
            if m.access == "public" and not m.is_static and not m.name.startswith("operator")
        ]
        function_rules = object_field(entry, "functions")
        for function in ir.functions:
            if function.qualified_name not in function_rules:
                continue
            rule = object_field(function_rules, function.qualified_name)
            hidden = rule.get("context_parameters", 0)
            if (
                not isinstance(hidden, int)
                or isinstance(hidden, bool)
                or hidden < 0
                or hidden > len(function.parameters)
            ):
                raise ValueError("Invalid native function context parameter count")
            exposed = copy.copy(function)
            exposed.parameters = function.parameters[hidden:]
            available.append(exposed)
        claimed: set[tuple[str, tuple[str, ...]]] = set()
        for group in object_list_field(entry, "groups"):
            namespace = identifier(group["namespace"])
            module = str(group.get("module", ""))
            if module:
                identifier(module)
            include = string_list_field(group, "include", ["*"])
            exclude = string_list_field(group, "exclude")
            rename = object_field(group, "rename")
            symbol = f"register_native_{index}_{namespace}"
            callback_type = f"NativeCallbacks_{index}_{namespace}"
            callback_fields: list[str] = []
            functions: dict[str, list[str]] = {}
            methods: list[JsonObject] = []
            for method in available:
                if not any(fnmatch.fnmatchcase(method.name, p) for p in include) or any(
                    fnmatch.fnmatchcase(method.name, p) for p in exclude
                ):
                    continue
                key = method.name, tuple(p.type_spelling for p in method.parameters)
                if key in claimed:
                    continue
                claimed.add(key)
                outputs: dict[int, tuple[str, tuple[str, str, str], bool]] = {}
                mapped: list[tuple[str, str, str]] = []
                for position, parameter in enumerate(method.parameters):
                    spelling = parameter.type_spelling
                    if not spelling.startswith("const ") and spelling.rstrip().endswith(("&", "*")):
                        bare = spelling.rstrip().rstrip("*& ").strip()
                        converted = conversion(bare, True)
                        outputs[position] = bare, converted, spelling.rstrip().endswith("*")
                        mapped.append(("", converted[1], ""))
                    else:
                        mapped.append(conversion(spelling))
                result = conversion(method.return_type, True)
                default_count = sum(p.default_value is not None for p in method.parameters)
                public_name = identifier(rename.get(method.name, method.name))
                overload_count = sum(m.name == method.name for m in available)
                suffix = (
                    "_" + hashlib.sha256(",".join(key[1]).encode()).hexdigest()[:8]
                    if overload_count > 1
                    else ""
                )
                callback_name = identifier(method.name + suffix)
                callback_fields.append(
                    f"std::function<{qualified(method.return_type)}({', '.join(qualified(p.type_spelling) for p in method.parameters)})> {callback_name};"
                )
                for count in range(len(mapped) - default_count, len(mapped) + 1):
                    params = [
                        f"{p[0]} arg{i}" for i, p in enumerate(mapped[:count]) if i not in outputs
                    ]
                    params.append("lua_State *L")
                    values = [
                        (("&" if outputs[i][2] else "") + f"output{i}")
                        if i in outputs
                        else p[2].format(expr=f"arg{i}")
                        for i, p in enumerate(mapped[:count])
                    ]
                    values.extend(str(p.default_value) for p in method.parameters[count:])
                    values = [qualified_default(value) for value in values]
                    call = f"function({', '.join(values)})"
                    statements = [
                        f"{qualified(kind)} output{i}{{}};"
                        for i, (kind, _, _) in outputs.items()
                        if i < count
                    ]
                    results: list[str] = []
                    result_types: list[str] = []
                    if method.return_type == "void":
                        statements.append(call + ";")
                    else:
                        statements.append("auto result = " + call + ";")
                        results.append(result[2].format(expr="result"))
                        result_types.append(result[1])
                    for i, (_, converted, _) in outputs.items():
                        if i < count:
                            results.append(converted[2].format(expr=f"output{i}"))
                            result_types.append(converted[1])
                    if len(results) == 1:
                        statements.append("return " + results[0] + ";")
                    elif results:
                        statements.append("return std::make_tuple(" + ", ".join(results) + ");")
                    body = " ".join(statements)
                    lua_result = (
                        result_types[0]
                        if len(result_types) == 1
                        else "(" + ", ".join(result_types) + ")"
                    )
                    functions.setdefault(public_name, []).append(
                        f'[function = callbacks.{callback_name}]({", ".join(params)}) {{ if (!function) {{ throw std::runtime_error("Host callback is not bound: {namespace}.{public_name}"); }} {body} }}'
                    )
                    methods.append(
                        {
                            "name": public_name,
                            "parameters": [
                                p[1] for i, p in enumerate(mapped[:count]) if i not in outputs
                            ],
                            "result": lua_result,
                            "callback": callback_name,
                            "native_name": method.name,
                            "native_arguments": [
                                qualified(p.type_spelling) for p in method.parameters
                            ],
                            "native_result": qualified(method.return_type),
                        }
                    )
            if not methods:
                raise ValueError(f"No native API methods selected for {namespace}")
            code = [
                *includes,
                '#include "native_apis.hpp"',
                "namespace qtluau {",
                f"void {symbol}(lua_State *L, const {callback_type} &callbacks) {{",
            ]
            if module:
                code.append(
                    f'if (pushModule(L, "{module}")) {{ lua_setglobal(L, "{namespace}"); }}'
                )
            code.append(
                f'auto cls = luabridge::getGlobalNamespace(L).beginNamespace("{namespace}");'
            )
            code.extend(
                f'cls.addFunction("{name}", {", ".join(overloads)});'
                for name, overloads in functions.items()
            )
            code.append("cls.endNamespace();")
            if module:
                code.extend(
                    [
                        f'lua_getglobal(L, "{namespace}");',
                        f'rememberModule(L, "{module}", -1);',
                        "lua_pop(L, 1);",
                    ]
                )
            if module and requires_module(config, module):
                code.extend(["lua_pushnil(L);", f'lua_setglobal(L, "{namespace}");'])
            code.extend(["}", "}"])
            filename = f"native_{index}_{namespace}.cpp"
            write(out / filename, "\n".join(code) + "\n")
            generated.add(filename)
            declarations.extend(
                [
                    "namespace qtluau {",
                    f"struct {callback_type} {{",
                    *callback_fields,
                    "};",
                    f"void {symbol}(lua_State *L, const {callback_type} &callbacks);",
                    "}",
                ]
            )
            metadata.append(
                {
                    "module": module,
                    "namespace": namespace,
                    "binding": "callbacks",
                    "context": [],
                    "name": namespace,
                    "native": "",
                    "callback_type": "qtluau::" + callback_type,
                    "base": "",
                    "constructible": False,
                    "methods": methods,
                    "properties": [],
                    "register": symbol,
                }
            )
        write(
            out / f"native_api_{index}_audit.json",
            json.dumps(
                {
                    "methods": [
                        {"namespace": e["namespace"], "members": e["methods"]} for e in metadata
                    ]
                },
                indent=2,
            )
            + "\n",
        )
        scan.unlink()
    for stale in out.glob("native_*.cpp"):
        if stale.name not in generated:
            stale.unlink()
    write(out / "native_apis.hpp", "\n".join(declarations) + "\n")
    return metadata
