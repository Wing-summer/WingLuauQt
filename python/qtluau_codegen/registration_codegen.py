# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Resolve adapter policy in Python and emit parameter-free C++ registrations."""

from __future__ import annotations

import argparse
import json
import pathlib

from .catalog import (
    BACKENDS,
    COMMON_ADAPTERS,
    COMMON_CONSTRUCTOR_SIGNATURES,
    COMMON_NATIVE_METHODS,
    DEFAULT_EXCLUDED_MEMBERS,
    DEFAULT_WIDGETS,
    EXCLUDED_ALWAYS,
    OBJECT_TYPE,
    VALUE_NATIVE_METHODS,
    VALUE_TYPES,
    VARIANT_METHODS,
    WIDGETS,
)
from .cpp_literals import qt_list
from .exclusions import excluded_method
from .extensions import write
from .function_naming import rename_registration_source
from .models import ClassDefinition, JsonObject, Method, object_field, string_list_field
from .selection import matches
from .type_mapping import mapped_type
from .type_policy import common_types


def emit_registrations(config: JsonObject, out: pathlib.Path, namespace: str = "qtluau") -> None:
    """Emit fixed registrations and a private entry-point header for validated policy.

    ``out`` contains disposable C++ output. Namespace and configuration errors are
    rejected before C++ compilation; no runtime configuration model is generated.
    """
    if any(not part.isidentifier() or not part.isascii() for part in namespace.split("::")):
        raise ValueError("Invalid registration namespace")
    qt = object_field(config, "qt")
    if qt.get("namespace", "qt") != "qt":
        raise ValueError("Qt registration requires qt.namespace = 'qt'")
    widgets = object_field(qt, "widgets")
    ui = object_field(qt, "ui_tools")
    policies = common_types(config)
    excludes = object_field(config, "exclude")
    members = [*DEFAULT_EXCLUDED_MEMBERS, *string_list_field(excludes, "members")]
    class_patterns = [
        *sorted(EXCLUDED_ALWAYS),
        *string_list_field(widgets, "exclude"),
        *string_list_field(excludes, "classes"),
    ]
    selected = set(
        string_list_field(widgets, "include") if "include" in widgets else DEFAULT_WIDGETS
    )
    selected.update(string_list_field(widgets, "extra_types"))
    selected.update(
        name
        for name, policy in policies.items()
        if name not in COMMON_ADAPTERS and name != "QVariant" and policy["enabled"]
    )
    for owner, key in (
        (widgets, "expose_qwidget_base"),
        (widgets, "hide_unselected"),
        (ui, "enabled"),
    ):
        if not isinstance(owner.get(key, True), bool):
            raise ValueError(f"{key} must be boolean")
    backends = BACKENDS
    generated = object_field(config, "_generated")
    additions = string_list_field(generated, "additions")
    backend_namespace = generated.get("backend_namespace", "")
    if not isinstance(backend_namespace, str) or not backend_namespace.isidentifier():
        raise ValueError("Native registration requires resolved SDK metadata")
    names = list(WIDGETS) + [name for name in additions if name not in WIDGETS]

    def rejected(name: str) -> bool:
        """Resolve canonical class rejection, including disabled aliases and bases."""
        if matches(name, class_patterns) or (name in policies and not policies[name]["enabled"]):
            return True
        base = (
            WIDGETS[name]["base"] if name in WIDGETS else ("QWidget" if name in additions else None)
        )
        return base is not None and rejected(base)

    def visible(name: str) -> bool:
        """Resolve the public Qt class surface while retaining required backends."""
        return not rejected(name) and (
            name == "QLayout"
            or (name == "QWidget" and widgets.get("expose_qwidget_base", True))
            or not widgets.get("hide_unselected", True)
            or name in selected
        )

    names = [name for name in names if name in {"QWidget", "QLayout"} or visible(name)]

    def method_enabled(name: str, method: str) -> bool:
        """Resolve capability and alias exclusions before emitting a registration."""
        policy = policies.get(name)
        if policy is not None:
            if "*" not in policy["methods"] and method not in policy["methods"]:
                return False
            if excluded_method(members, policy["alias"], method):
                return False
        return not excluded_method(members, name, method)

    def constructor(name: str, definition: ClassDefinition, cpp: str) -> list[str]:
        """Render the selected constructor overload group with exact arity checks."""
        signatures: list[str] = []
        for parameters in definition["constructors"]:
            if not parameters:
                args: list[str] = []
                cpp_signatures = ["void (*)()"]
            elif len(parameters) == 1 and parameters[0][1] in {"string", "$self"}:
                if parameters[0][1] == "$self":
                    continue
                args = [COMMON_CONSTRUCTOR_SIGNATURES.get(name, "QString")]
                value_type = cpp if name in COMMON_ADAPTERS else "QtValueRef<QString>"
                cpp_signatures = [
                    "void (*)(const std::string &)",
                    f"void (*)(const {value_type} &)",
                ]
            else:
                args = ["int" for _ in parameters]
                cpp_signatures = ["void (*)(" + ", ".join(args) + ")"]
            if not excluded_method(members, name, "new", args):
                signatures.extend(cpp_signatures)
        if signatures == ["void (*)()"]:
            signatures *= 2
        return (
            ["cls.template addConstructor<" + ", ".join(signatures) + ">();"] if signatures else []
        )

    def method_lines(name: str, methods: list[Method], cpp: str) -> list[str]:
        """Render method pointers from the discovered wrapper declarations."""
        result: list[str] = []
        for method, params, returns in methods:
            if not method_enabled(name, method):
                continue
            if method.startswith("findChild") and returns.startswith("_qt_"):
                target = returns.removeprefix("_qt_")
                if target != "QWidget" and not (target in selected and not rejected(target)):
                    continue
            native: object = method
            if not native.isidentifier():
                raise ValueError(f"Invalid adapted method name: {name}::{method}")
            if method.startswith("findChild") and returns.startswith("_qt_"):
                target = returns.removeprefix("_qt_")
                target_cpp = BACKENDS[target]["cpp_type"]
                code = f'[](const QtWidgetRef &self, const std::string &name) {{ auto *child = self.get()->findChild<{target} *>(toQString(name)); if (!child) throw std::runtime_error("No child of the requested type and name"); return {target_cpp}(child, false); }}'
            elif name in VALUE_TYPES and returns == "string" and not params:
                code = f"[](const {cpp} &self) {{ return toUtf8String(self.{native}()); }}"
            elif name in VALUE_TYPES and len(params) == 1 and params[0][1] == "string":
                code = f"[]({cpp} &self, const std::string &text) {{ self.{native}(toQString(text)); }}"
            elif (
                len(params) == 1
                and params[0][1] in {"string", "string | $self"}
                and returns == "()"
            ):
                kinds = ("std::string", cpp if name in COMMON_ADAPTERS else "QtValueRef<QString>")
                code = ", ".join(
                    f"static_cast<void ({cpp}::*)(const {kind} &)>(&{cpp}::{native})"
                    for kind in kinds
                )
            else:
                code = f"&{cpp}::{native}"
            result.append(f'cls.addFunction("{method}", {code});')
        return result

    out.mkdir(parents=True, exist_ok=True)
    prefix = [
        '#include "static_registration.hpp"',
        '#include "qtluau/widget_wrappers.hpp"',
        '#include "qtluau/value_conversion.hpp"',
        '#include "qtluau/ui_support.hpp"',
        "#include <stdexcept>",
        "#include <QtWidgets/QtWidgets>",
        "namespace qtluau { int constructVariant(lua_State *L);",
        '#include "qt_methods.inc"',
        "}",
        f"namespace {namespace} {{",
        "using namespace ::qtluau;",
        "namespace {",
    ]
    common = list(prefix)
    for name, definition in COMMON_ADAPTERS.items():
        cpp = object_field(backends, name)["cpp_type"]
        if not isinstance(cpp, str):
            raise ValueError(f"Invalid native backend: {name}")
        alias = policies[name]["alias"]
        common.extend(
            [
                f"void register_{name}(lua_State *L) {{",
                f'auto cls = luabridge::getGlobalNamespace(L).beginClass<{cpp}>("{alias}");',
            ]
        )
        common.extend(constructor(name, definition, cpp))
        native_groups: dict[str, list[str]] = {}
        for value_method in COMMON_NATIVE_METHODS[name]:
            method = value_method.native
            if method_enabled(name, method["name"]) and not excluded_method(
                members, name, method["name"], method["args"]
            ):
                native_groups.setdefault(method["name"], []).append(value_method.lambda_code(cpp))
        for method_name, overloads in native_groups.items():
            common.append(f'cls.addFunction("{method_name}", ' + ", ".join(overloads) + ");")
        common.extend(["guardClassMethods(L, cls);", "cls.endClass();", "}"])
    common.extend(
        [
            "}",
            "void registerCommonBindings(lua_State *L) {",
            'if (!L) { throw std::invalid_argument("lua_State is null"); }',
        ]
    )
    for name in COMMON_ADAPTERS:
        common.extend(
            [
                f'lua_getfield(L, LUA_REGISTRYINDEX, "qtluau.binding.class.{name}");',
                "const bool exists_" + name + " = !lua_isnil(L, -1); lua_pop(L, 1);",
                f'if (exists_{name}) {{ throw std::runtime_error("Bindings already registered"); }}',
            ]
        )
    for name in COMMON_ADAPTERS:
        alias = policies[name]["alias"]
        common.extend(
            [
                f"register_{name}(L);",
                f'lua_getglobal(L, "{alias}");',
                f'lua_setfield(L, LUA_REGISTRYINDEX, "qtluau.binding.class.{name}");',
            ]
        )
        if rejected(name):
            common.extend(["lua_pushnil(L);", f'lua_setglobal(L, "{alias}");'])
    variant_methods = VARIANT_METHODS
    common.append(
        'auto cls = luabridge::getGlobalNamespace(L).beginClass<VariantBox>("_qtluau_QVariant");'
    )
    for name in variant_methods:
        if method_enabled("QVariant", name):
            common.append(f'cls.addFunction("{name}", &VariantBox::{name});')
    common.extend(
        [
            "guardClassMethods(L, cls);",
            "cls.endClass();",
            'lua_pushnil(L); lua_setglobal(L, "_qtluau_QVariant");',
        ]
    )
    common.append(
        "lua_newtable(L);"
        if excluded_method(members, "QVariant", "new", [])
        else 'lua_pushcfunction(L, ::qtluau::constructVariant, "QVariant");'
    )
    common.extend(
        [
            'lua_pushvalue(L, -1); lua_setfield(L, LUA_REGISTRYINDEX, "qtluau.binding.class.QVariant");'
        ]
    )
    common.append(
        "lua_pop(L, 1);"
        if rejected("QVariant")
        else f'lua_setglobal(L, "{policies["QVariant"]["alias"]}");'
    )
    common.extend(["}", "}"])
    write(out / "static_common.cpp", rename_registration_source(config, "\n".join(common) + "\n"))

    code = list(prefix)
    code.extend(
        [
            "void register_QObject(lua_State *L) {",
            'auto cls = luabridge::getGlobalNamespace(L).beginNamespace("qt").beginClass<QObjectRef>("QObject");',
        ]
    )
    code.extend(method_lines("QObject", OBJECT_TYPE["methods"], "QObjectRef"))
    code.extend(["guardClassMethods(L, cls);", "cls.endClass();", "}"])

    for name, definition in VALUE_TYPES.items():
        if rejected(name):
            continue
        code.extend(
            [
                f"void register_{name}(lua_State *L) {{",
                f'auto cls = luabridge::getGlobalNamespace(L).beginNamespace("qt").beginClass<{name}>("{name}");',
            ]
        )
        code.extend(constructor(name, definition, name))
        groups: dict[str, list[str]] = {}
        for method, count in VALUE_NATIVE_METHODS[name]:
            if not method_enabled(name, method["name"]) or excluded_method(
                members, name, method["name"], method["args"]
            ):
                continue
            arguments = [mapped_type(arg) for arg in method["args"][:count]]
            result = mapped_type(method["result"], True)
            if result is None or any(arg is None for arg in arguments):
                raise ValueError("Unsupported discovered value signature")
            checked = [arg for arg in arguments if arg is not None]
            params = ", ".join(f"{arg[0]} arg{i}" for i, arg in enumerate(checked))
            values = ", ".join(arg[2].format(expr=f"arg{i}") for i, arg in enumerate(checked))
            call = f"self.{method['name']}({values})"
            expression = (
                f"toUtf8String({call})"
                if method["result"] == "QString"
                else result[2].format(expr=call)
            )
            state = ", lua_State *L" if "qtToLua" in expression else ""
            receiver = ("const " if method["const"] else "") + name + " &self"
            body = ("" if result[0] == "void" else "return ") + expression + ";"
            groups.setdefault(method["name"], []).append(
                f"[]({receiver}{', ' if params else ''}{params}{state}) {{ {body} }}"
            )
        for method_name, overloads in groups.items():
            code.append(
                f'cls.addFunction("{method_name}", ' + ", ".join(dict.fromkeys(overloads)) + ");"
            )
        code.extend(["guardClassMethods(L, cls);", "cls.endClass();", "}"])
    for name in names:
        fallback: ClassDefinition = {"base": "QWidget", "methods": [], "constructors": [[]]}
        widget_definition: ClassDefinition = WIDGETS.get(name, fallback)
        backend = object_field(backends, name)
        cpp_object: object = backend.get("cpp_type", f"QtTypedWidgetRef<{name}>")
        if not isinstance(cpp_object, str):
            raise ValueError(f"Invalid native backend: {name}")
        cpp = cpp_object
        typed = cpp.startswith(("QtTypedWidgetRef<", "QtTypedLayoutRef<"))
        if typed:
            code.append(f"template <class Native = {name}>")
            cpp = cpp.split("<", 1)[0] + "<Native>"
        code.append(f"void register_{name}(lua_State *L) {{")
        base = widget_definition["base"]
        base_cpp = "QtWidgetRef" if base == "QWidget" else "QtLayoutRef"
        start = f"beginClass<{cpp}>" if base is None else f"deriveClass<{cpp}, {base_cpp}>"
        code.append(
            f'auto cls = luabridge::getGlobalNamespace(L).beginNamespace("qt").{start}("{name}");'
        )
        ctors = constructor(name, widget_definition, cpp)
        if typed:
            # Only native C++ constructibility remains a compile-time type check.
            code.append("if constexpr (std::is_default_constructible_v<Native>) {")
            if not excluded_method(members, name, "new", []):
                code.append("cls.template addConstructor<void (*)(), void (*)()>();")
            code.append("}")
            text_definition: ClassDefinition = {
                "base": None,
                "methods": [],
                "constructors": [params for params in widget_definition["constructors"] if params],
            }
            text_ctors = constructor(name, text_definition, cpp)
            if text_ctors:
                # Register empty and text signatures together whenever both exist.
                code.append("if constexpr (std::is_constructible_v<Native, const QString &>) {")
                code.extend(ctors)
                code.append("}")
        else:
            code.extend(ctors)
        code.extend(method_lines(name, widget_definition["methods"], cpp))
        if base in {"QWidget", "QLayout"} or name in {"QWidget", "QLayout"}:
            code.append(f"::qtluau::{backend_namespace}::extendDiscoveredWidget(cls);")
        code.extend(["guardClassMethods(L, cls);", "cls.endClass();", "}"])
    code.extend(
        [
            "}",
            "void registerQtBindings(lua_State *L) {",
            'if (!L) { throw std::invalid_argument("lua_State is null"); }',
        ]
    )
    code.append("register_QObject(L);")
    for name in VALUE_TYPES:
        if not rejected(name):
            code.append(f"register_{name}(L);")
    code.append("register_QWidget(L);")
    code.extend(f"register_{name}(L);" for name in names if name != "QWidget")
    code.extend(['lua_getglobal(L, "qt");', "const int table = lua_gettop(L);"])
    for name, policy in policies.items():
        if rejected(name):
            continue
        if name not in backends and name not in additions:
            raise ValueError(f"No binding backend: {name}")
        code.extend(
            [
                f'lua_getfield(L, LUA_REGISTRYINDEX, "qtluau.binding.class.{name}");',
                "if (lua_isnil(L, -1)) { lua_pop(L, 1);",
                f'lua_getfield(L, table, "{name}");',
                "}",
                "lua_pushvalue(L, -1);",
                f'lua_setglobal(L, "{policy["alias"]}");',
                f'lua_rawsetfield(L, table, "{name}");',
            ]
        )
    code.extend(['pushNullValue(L); lua_rawsetfield(L, table, "null");'])
    for name in names:
        if not visible(name):
            code.append(f'lua_pushnil(L); lua_rawsetfield(L, table, "{name}");')
    code.append("lua_pop(L, 1);")
    if ui.get("enabled", True):
        code.extend(
            [
                'auto uiNamespace = luabridge::getGlobalNamespace(L).beginNamespace("qt");',
                'uiNamespace.addFunction("loadUiWidgetXml", &::qtluau::detail::loadUiXml);',
                f'uiNamespace.addFunction("loadUiWidgetFile", [roots = QStringList{qt_list(string_list_field(ui, "allowed_roots"))}](const std::string &path) {{ return ::qtluau::detail::loadUiFile(path, roots); }});',
                "uiNamespace.endNamespace();",
            ]
        )
    code.extend(
        [
            "}",
            f"QStringList allowedUiRoots() {{ return {qt_list(string_list_field(ui, 'allowed_roots'))}; }}",
            "}",
        ]
    )
    write(out / "static_widgets.cpp", rename_registration_source(config, "\n".join(code) + "\n"))
    guard = "QTLUAU_GENERATED_" + namespace.replace("::", "_").upper() + "_STATIC_REGISTRATION_HPP"
    header = [
        f"#ifndef {guard}",
        f"#define {guard}",
        '#include "qtluau/bindings.hpp"',
        f"namespace {namespace} {{",
        "void registerCommonBindings(lua_State *L);",
        "void registerQtBindings(lua_State *L);",
        "QStringList allowedUiRoots();",
        "}",
        f"#endif // {guard}",
    ]
    write(out / "static_registration.hpp", "\n".join(header) + "\n")


def main() -> None:
    """Generate registrations from an already resolved policy, optionally in a namespace."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--namespace", default="qtluau")
    args = parser.parse_args()
    config: JsonObject = json.loads(args.config.read_text())
    if "_generated" in config:
        emit_registrations(config, args.out, args.namespace)
    else:
        from .qt_pipeline import emit

        emit(config, args.out, args.config.parent, args.namespace)


if __name__ == "__main__":
    main()
