#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Resolve the Qt SDK and compile binding policy into disposable build artifacts.

Requires the tsujikiri dependency declared by the Python package.
No machine-specific header paths or source entries belong in binding policy.
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

from .api_baseline import apply_baseline
from .catalog import (
    BACKENDS,
    DEFAULT_EXCLUDED_MEMBERS,
    DEFAULT_WIDGETS,
    EXCLUDED_ALWAYS,
    LAYOUT_POINTERS,
    OBJECT_POINTERS,
    TYPE_DEFAULTS,
    WIDGET_POINTERS,
    WIDGETS,
)
from .exclusions import excluded_method
from .extensions import definitions as extension_definitions
from .extensions import emit_extensions
from .function_naming import rename_registration_source, rename_registrations
from .header_guards import guard_headers
from .models import ClassDefinition, JsonObject, NativeMethod, object_field, string_list_field
from .sdk_version import selected_version, validate_version
from .selection import matches, resolve
from .type_mapping import mapped_type
from .type_policy import common_types

CPP_ITERATORS = {
    "begin",
    "end",
    "cbegin",
    "cend",
    "rbegin",
    "rend",
    "crbegin",
    "crend",
    "constBegin",
    "constEnd",
    "erase",
    "insertIterator",
}

LUA_KEYWORDS = set(
    "and break do else elseif end false for function if in local nil not or repeat return then true until while".split()
)


def write(path: pathlib.Path, content: str) -> None:
    """Write UTF-8 text only when its content differs from the existing file."""
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def emit(
    config: JsonObject,
    out: pathlib.Path,
    base: pathlib.Path | None = None,
    registration_namespace: str = "qtluau",
) -> JsonObject:
    """Discover the selected SDK surface and emit resolved registration inputs."""
    validate_version(config)
    apply_baseline(config, selected_version())
    lsp = object_field(config, "lsp")
    if lsp.get("server", "luau-lsp") != "luau-lsp" or lsp.get("syntax", "luau") != "luau":
        raise ValueError(
            "Definition output requires lsp.server=luau-lsp and lsp.syntax=luau; tsujikiri luals is a different format"
        )
    common_types(config)
    resolved, classes, flags, report = resolve(config)
    out.mkdir(parents=True, exist_ok=True)
    # Obsolete dynamic registration inputs must not survive incremental generation.
    for filename in (
        "common_types.inc",
        "default_excluded_members.inc",
        "runtime_policy.hpp",
        "default_widgets.inc",
        "excluded_classes.inc",
        "qt_selected.inc",
        "qt_supported.inc",
        "qt_ancestors.inc",
        "qt_typed_widgets.inc",
        "qt_managed.inc",
        "qt_widgets.inc",
        "qt_adapter_methods.inc",
        "qt_child_finders.inc",
        "legacy_common_keys.inc",
    ):
        (out / filename).unlink(missing_ok=True)
    selected = report.get(
        "selected",
        object_field(object_field(config, "qt"), "widgets").get("include", DEFAULT_WIDGETS),
    )
    selected = list(
        dict.fromkeys(
            [
                *selected,
                *string_list_field(
                    object_field(object_field(config, "qt"), "widgets"), "extra_types"
                ),
                *[
                    name
                    for name, policy in common_types(config).items()
                    if policy["kind"] == "qt" and policy["enabled"]
                ],
            ]
        )
    )
    additions = [
        n
        for n in selected
        if n not in WIDGETS and n not in TYPE_DEFAULTS and n not in ("QColor", "QFont")
    ]
    # Internal/base adapter classes are always compiled, even with a restricted policy.
    backend_namespace = (
        "generated_"
        + hashlib.sha256(
            (
                registration_namespace
                + json.dumps(
                    {key: config.get(key, {}) for key in ("qt", "common", "exclude", "naming")},
                    sort_keys=True,
                )
            ).encode()
        ).hexdigest()[:12]
    )
    metadata: dict[str, ClassDefinition] = {}
    declarations = [
        "// Generated; do not edit.",
        f"#ifndef QTLUAU_GENERATED_{backend_namespace.upper()}_QT_METHODS_INC",
        f"#define QTLUAU_GENERATED_{backend_namespace.upper()}_QT_METHODS_INC",
        f"namespace {backend_namespace} {{",
    ]
    generated_sources: set[str] = set()
    skipped: list[JsonObject] = []
    excluded = DEFAULT_EXCLUDED_MEMBERS + string_list_field(
        object_field(config, "exclude"), "members"
    )
    excluded_classes = string_list_field(object_field(config, "exclude"), "classes")
    disabled_types = {
        name for name, policy in common_types(config).items() if not policy["enabled"]
    }
    active_wrappers = set(selected) | {"QWidget"}
    if not object_field(object_field(resolved, "qt"), "widgets").get("hide_unselected", True):
        active_wrappers.update(WIDGETS)
    active_wrappers.add("QLayout")
    for name in sorted(active_wrappers - {"QFont", "QColor"}):
        data = classes.get(name)
        adapter = WIDGETS.get(name)
        existing = {m[0] for m in adapter["methods"]} if adapter is not None else set[str]()
        # QWidget methods already inherited by all wrappers must not be reintroduced.
        if name != "QWidget":
            existing.update(m[0] for m in WIDGETS["QWidget"]["methods"])
        groups: dict[str, list[tuple[NativeMethod, list[tuple[str, str, str]]]]] = {}

        def inherited_methods(current: str, seen: set[str] | None = None) -> list[NativeMethod]:
            """Collect inherited method names for registration deduplication."""
            seen = set() if seen is None else seen
            if current in seen:
                return []
            seen.add(current)
            current_data = classes.get(current)
            if current_data is None:
                return []
            methods = list(current_data["methods"])
            for base in current_data["bases"]:
                if base not in ("QWidget", "QLayout") and (
                    base != "QObject" or current in {"QWidget", "QLayout"}
                ):
                    own_names = {method["name"] for method in current_data["methods"]}
                    methods.extend(
                        method
                        for method in inherited_methods(base, seen)
                        if method["name"] not in own_names
                    )
            return methods

        signatures: set[tuple[str, tuple[str, ...], bool]] = set()
        for method in inherited_methods(name):
            signature = (method["name"], tuple(method["args"]), method["const"])
            if signature in signatures:
                continue
            signatures.add(signature)
            mn = method["name"]
            if mn in CPP_ITERATORS or any(
                "iterator" in t for t in [method["result"], *method["args"]]
            ):
                skipped.append(
                    {
                        "class": name,
                        "method": method,
                        "reason": "C++ iterator API; containers use Luau table iteration",
                    }
                )
                continue
            if mn in LUA_KEYWORDS:
                skipped.append({"class": name, "method": method, "reason": "Luau reserved word"})
                continue
            if mn in existing or mn.startswith("operator") or method["static"]:
                continue
            if (
                method["variadic"]
                or method["deprecated"]
                or excluded_method(excluded, name, mn, method["args"])
                or excluded_method(excluded, method["owner"], mn, method["args"])
                or any(
                    dep in disabled_types or matches(dep, excluded_classes)
                    for dep in ("QColor", "QFont")
                    if dep in " ".join([method["result"], *method["args"]])
                )
            ):
                continue
            if any(matches(dep, excluded_classes) for dep in re.findall(r"\bQ[A-Za-z0-9_]+\b", " ".join([method["result"], *method["args"]]))):
                skipped.append({"class": name, "method": method, "reason": "excluded signature type"})
                continue
            for count in range(
                method.get("minimum_args", len(method["args"])), len(method["args"]) + 1
            ):
                types = [
                    mapped_type(
                        method["result"], True, OBJECT_POINTERS, WIDGET_POINTERS, LAYOUT_POINTERS
                    ),
                    *[
                        mapped_type(
                            arg,
                            object_types=OBJECT_POINTERS,
                            widget_types=WIDGET_POINTERS,
                            layout_types=LAYOUT_POINTERS,
                        )
                        for arg in method["args"][:count]
                    ],
                ]
                if not all(types):
                    skipped.append(
                        {"class": name, "method": method, "reason": "unsupported signature"}
                    )
                    continue
                checked_types = [t for t in types if t is not None]
                if any(
                    [t[0] for t in existing_types[1:]] == [t[0] for t in checked_types[1:]]
                    for _, existing_types in groups.get(mn, [])
                ):
                    continue
                groups.setdefault(mn, []).append((method, checked_types))
        wrapper = BACKENDS.get(name, {}).get("cpp_type", f"QtTypedWidgetRef<{name}>")
        declaration = f'void extendDiscoveredWidget(decltype(luabridge::getGlobalNamespace(static_cast<lua_State*>(nullptr)).beginClass<{wrapper}>(""))& cls)'
        declarations.append(declaration + ";")
        code = [
            '#include "qtluau/bindings.hpp"',
            '#include "qtluau/widget_wrappers.hpp"',
            '#include "qtluau/value_conversion.hpp"',
            "#include <QtWidgets/QtWidgets>",
            "#include <QtGui/QtGui>",
            "#include <QtCore/QtCore>",
            f"namespace qtluau::{backend_namespace} {{",
            declaration + " {",
            "    (void)cls;",
        ]
        accessors = object_field(object_field(config, "qt"), "content_accessors")
        if any(accessors.get(method["owner"] + "::" + method["name"]) in {"menu", "menu_widget", "set_menu"}
               for overloads in groups.values() for method, _ in overloads):
            code.insert(0, '#include "qtluau/window_menu.hpp"')
        methods: list[tuple[str, list[tuple[str, str]], str]] = []
        for mn, overloads in sorted(groups.items()):
            lambdas: list[str] = []
            for method, types in overloads:
                params = ", ".join(f"{t[0]} arg{i}" for i, t in enumerate(types[1:]))
                callargs = ", ".join(t[2].format(expr=f"arg{i}") for i, t in enumerate(types[1:]))
                owner = method["owner"]
                cast = f"{method['result']} ({owner}::*)({', '.join(method['args'])})" + (
                    " const" if method["const"] else ""
                )
                expr = (
                    f"(native->*static_cast<{cast}>(&{owner}::{mn}))({callargs})"
                    if len(types) - 1 == len(method["args"])
                    else f"native->{owner}::{mn}({callargs})"
                )
                if owner + "::" + mn in string_list_field(object_field(config, "qt"), "content_methods"):
                    expr = expr.replace("native->", "qtluau::widgetContentTarget(native)->")
                operation = object_field(object_field(config, "qt"), "content_accessors").get(owner + "::" + mn)
                if operation == "get":
                    expr = "qtluau::windowContentTarget(native)"
                elif operation == "set":
                    expr = f"qtluau::replaceWidgetContentTarget(native, {callargs})"
                elif operation == "take":
                    expr = "qtluau::takeWidgetContentTarget(native)"
                elif operation in {"menu", "menu_widget"}:
                    expr = "qtluau::windowMenuTarget(native, " + ("true" if operation == "menu" else "false") + ")"
                elif operation == "set_menu":
                    expr = f"qtluau::replaceWindowMenuTarget(native, {callargs})"
                elif operation is not None:
                    raise ValueError("Unsupported window content operation: " + str(operation))
                statement = ("qtluau::qtOwnedToLua(L, " + expr + ")" if operation == "take" else types[0][2].format(expr=expr))
                body = ("" if types[0][0] == "void" else "return ") + statement + ";"
                state_parameter = ", lua_State* L" if "qtToLua" in types[0][2] else ""
                lambdas.append(
                    f'[]({wrapper}& self{", " if params else ""}{params}{state_parameter}) {{ auto* native = qobject_cast<{name}*>(self.get()); if (!native) throw std::runtime_error("Qt widget type mismatch"); {body} }}'
                )
                methods.append(
                    (
                        mn,
                        [(f"arg{i}", t[1]) for i, t in enumerate(types[1:])],
                        types[0][1],
                    )
                )
            code.append(f'        cls.addFunction("{mn}", ' + ", ".join(lambdas) + ");")
        code.extend(["}", "}"])
        generated_sources.add(f"qt_auto_{name}.cpp")
        write(
            out / f"qt_auto_{name}.cpp", rename_registration_source(config, "\n".join(code) + "\n")
        )
        metadata[name] = {
            "methods": methods,
            "base": adapter["base"] if adapter is not None else "QWidget",
            "constructors": [[]]
            if data is not None and data["default_ctor"] and name in additions
            else [],
        }
    for stale in out.glob("qt_auto_*.cpp"):
        if stale.name not in generated_sources:
            stale.unlink()
    declarations.extend(["}", "#endif"])
    write(out / "qt_methods.inc", "\n".join(declarations) + "\n")
    managed = sorted((set(WIDGETS) | set(additions)) - {"QColor", "QFont"})
    ui_widgets = [
        name
        for name in managed
        if (name == "QWidget" or name in additions or WIDGETS[name]["base"] == "QWidget")
        and not matches(name, set(EXCLUDED_ALWAYS) | set(excluded_classes))
    ]
    from .ui_codegen import emit_ui_loader

    emit_ui_loader(resolved, out, ui_widgets)
    (out / "qt_ui_widgets.inc").unlink(missing_ok=True)
    resolved["_extensions"] = emit_extensions(config, out, base or pathlib.Path.cwd())
    write(out / "qt_extensions.d.luau", extension_definitions(resolved["_extensions"]))
    resolved["_generated"] = {
        "types": metadata,
        "additions": additions,
        "backend_namespace": backend_namespace,
    }
    write(out / "resolved-bindings.json", json.dumps(resolved, indent=2) + "\n")
    report["unsupported_methods"] = skipped
    write(out / "discovery-report.json", json.dumps(report, indent=2) + "\n")
    shim = out / "qt_scan.hpp"
    write(
        shim,
        "\n".join(
            f"#include <{m}/{m}>"
            for m in object_field(object_field(config, "qt"), "discovery").get(
                "modules", ["QtCore", "QtGui", "QtWidgets"]
            )
        )
        + "\n",
    )
    # JSON is valid YAML 1.2. Only this generated tsujikiri input contains source/path.
    backend = {
        "source": {"path": str(shim.resolve()), "parse_args": ["-std=c++17", *flags]},
        "filters": {
            "classes": {"whitelist": sorted(set(selected) | {"QFont", "QColor"})},
            "methods": {"global_blacklist": ["moveToThread", "deleteLater"]},
        },
    }
    write(out / "qt_tsujikiri.input.yml", json.dumps(backend, indent=2) + "\n")
    from .registration_codegen import emit_registrations

    emit_registrations(resolved, out, registration_namespace)
    (out / "wrapper_forwarders.cpp").unlink(missing_ok=True)
    rename_registrations(config, out)
    guard_headers(out, registration_namespace)
    return resolved


def main() -> int:
    """Run SDK discovery from CLI policy and return an exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    try:
        resolved = emit(
            json.loads(args.config.read_text()), args.out.resolve(), args.config.resolve().parent
        )
        count = len(
            object_field(object_field(resolved, "qt"), "widgets").get("include", DEFAULT_WIDGETS)
        )
        print(f"Qt policy resolved: {count} types; artifacts in {args.out}")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Qt pipeline failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
