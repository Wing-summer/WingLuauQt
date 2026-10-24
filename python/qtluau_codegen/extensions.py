# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate user QObject APIs from Qt moc metadata, including private slots."""

from __future__ import annotations

import fnmatch
import glob
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

from .assets import support_root
from .class_codegen import render_members
from .discovery import discover_sdk
from .exclusions import excluded_method
from .member_scan import scan_members
from .models import JsonObject, object_field, object_list_field, string_list_field
from .type_policy import KEYWORDS


def write(path: pathlib.Path, content: str) -> None:
    """Write a generated file only if its UTF-8 content changed."""
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def qt_moc() -> str:
    # Do not accidentally pick the Qt 5 moc from PATH when binding Qt 6.
    """Locate the meta-object compiler belonging to the selected Qt SDK."""
    candidates: list[str] = []
    if shutil.which("pkg-config"):
        proc = subprocess.run(
            ["pkg-config", "--variable=libexecdir", "Qt6Core"], capture_output=True, text=True
        )
        if proc.returncode == 0:
            candidates.append(str(pathlib.Path(proc.stdout.strip()) / "moc"))
    for name in ("qtpaths6", "qtpaths", "qmake6", "qmake"):
        tool = shutil.which(name)
        if tool:
            proc = subprocess.run(
                [tool, "--query" if "qtpaths" in name else "-query", "QT_INSTALL_LIBEXECS"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                candidates.append(str(pathlib.Path(proc.stdout.strip()) / "moc"))
    candidates.extend(tool for name in ("moc6", "moc") if (tool := shutil.which(name)))
    for candidate in candidates:
        if pathlib.Path(candidate).is_file():
            version = subprocess.run([candidate, "-v"], capture_output=True, text=True)
            if re.search(r"moc 6\.", version.stdout + version.stderr):
                return candidate
    raise ValueError("Qt 6 moc executable not found in the SDK")


def identifier(value: object) -> str:
    """Validate a configured C++ identifier or raise ValueError."""
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value)
        or value in KEYWORDS
    ):
        raise ValueError(f"Invalid Luau identifier: {value}")
    return value


def paths(base: pathlib.Path, patterns: list[str]) -> list[pathlib.Path]:
    """Resolve configured input globs against the explicit source root."""
    result: set[pathlib.Path] = set()
    for pattern in patterns:
        found = [pathlib.Path(p).resolve() for p in glob.glob(str(base / pattern), recursive=True)]
        if not found:
            raise ValueError(f"Extension input did not match any files: {pattern}")
        result.update(found)
    return sorted(result)


def emit_extensions(config: JsonObject, out: pathlib.Path, base: pathlib.Path) -> list[JsonObject]:
    """Scan configured QObject classes and emit wrappers and metadata."""
    entries = object_list_field(config, "extensions")
    manifest_id = hashlib.sha256(
        (json.dumps(entries, sort_keys=True) + str(base)).encode()
    ).hexdigest()[:12]
    metadata: list[JsonObject] = []
    declarations = ["#pragma once", '#include "qtluau/bindings.hpp"', "namespace qtluau {"]
    registrations: list[str] = []
    sources: set[pathlib.Path] = set()
    inputs: set[pathlib.Path] = set()
    input_patterns: set[str] = set()
    include_dirs: set[pathlib.Path] = set()
    defines: set[str] = set()
    generated: set[str] = set()
    exposed_names: set[tuple[str, str]] = set()
    native_names: set[str] = set()
    friend_names: set[str] = set()
    for entry in entries:
        if set(entry) - {
            "headers",
            "sources",
            "include_dirs",
            "defines",
            "namespace",
            "module",
            "classes",
            "compile_moc",
        }:
            raise ValueError("Unknown extension option")
        for field in ("headers", "sources"):
            input_patterns.update(
                str(base / pattern) for pattern in string_list_field(entry, field)
            )
        compile_moc = entry.get("compile_moc", True)
        if not isinstance(compile_moc, bool):
            raise ValueError("compile_moc must be boolean")
        module_value = entry.get("module", entry.get("namespace", ""))
        module = "" if module_value == "" else identifier(module_value)
        namespace_value = entry.get("namespace", module)
        namespace = "" if namespace_value == "" else identifier(namespace_value)
        if module and namespace != module:
            raise ValueError("Named modules must use their module name as namespace")
        if namespace == "_G":
            raise ValueError("Use an empty module name for public/global bindings")
        headers = paths(base, string_list_field(entry, "headers"))
        if not headers:
            raise ValueError("Extension headers must not be empty")
        directories = paths(base, string_list_field(entry, "include_dirs"))
        entry_defines = string_list_field(entry, "defines")
        include_dirs.update(directories)
        defines.update(entry_defines)
        sources.update(paths(base, string_list_field(entry, "sources")))
        rules = object_field(entry, "classes")
        seen_classes: set[str] = set()
        moc = qt_moc()
        flags = [
            *discover_sdk(["QtCore", "QtGui", "QtWidgets"]),
            "-I" + str(support_root() / "include"),
            *[f"-I{d}" for d in directories],
            *[f"-D{d}" for d in entry_defines],
        ]
        for header in headers:
            inputs.add(header)
            native_members = scan_members(header, flags)
            key = hashlib.sha256((str(header) + namespace).encode()).hexdigest()[:12]
            moc_key = hashlib.sha256(json.dumps([str(header), flags]).encode()).hexdigest()[:12]
            moc_name = f"qt_ext_moc_{moc_key}.cpp"
            moc_output = out / moc_name
            with tempfile.TemporaryDirectory(prefix="qtluau-moc-") as temporary:
                staged = pathlib.Path(temporary) / moc_name
                proc = subprocess.run(
                    [
                        moc,
                        *flags,
                        "--output-json",
                        "-f",
                        str(header),
                        "-o",
                        str(staged),
                        str(header),
                    ],
                    capture_output=True,
                    text=True,
                )
                if proc.returncode:
                    raise ValueError(f"moc failed for {header}:\n{proc.stderr}")
                json_path = staged.with_suffix(".cpp.json")
                if not json_path.exists():
                    raise ValueError(f"No Q_OBJECT metadata in extension header: {header}")
                document: JsonObject = json.loads(json_path.read_text())
                if compile_moc:
                    write(moc_output, staged.read_text())
                write(moc_output.with_suffix(".cpp.json"), json_path.read_text())
            if compile_moc:
                generated.add(moc_name)
            for record in object_list_field(document, "classes"):
                native: str = record["qualifiedClassName"]
                if native not in rules:
                    continue
                class_exclusions = string_list_field(object_field(config, "exclude"), "classes")
                if any(fnmatch.fnmatchcase(native, pattern) for pattern in class_exclusions):
                    seen_classes.add(native)
                    continue
                rule = object_field(rules, native)
                functions = rule.get("binding", "class") == "functions"
                if rule.get("binding", "class") not in {"class", "functions"}:
                    raise ValueError("binding must be class or functions")
                if native in native_names and not functions:
                    raise ValueError(f"Native extension type registered twice: {native}")
                if not functions:
                    native_names.add(native)
                if rule.get("non_public") == "friend":
                    if native in friend_names:
                        raise ValueError(
                            "Repeated friend binding requires separate native facade classes"
                        )
                    friend_names.add(native)
                if not record.get("object", False):
                    raise ValueError(f"Extension class requires Q_OBJECT: {native}")
                seen_classes.add(native)
                rule = object_field(rules, native)
                if set(rule) - {
                    "name",
                    "expose_base",
                    "constructible",
                    "methods",
                    "access",
                    "members",
                    "non_public",
                    "binding",
                    "include",
                    "exclude",
                    "context",
                }:
                    raise ValueError(f"Unknown extension class option for {native}")
                name = identifier(rule.get("name", record["className"]))
                if (namespace, name) in exposed_names:
                    raise ValueError(f"Duplicate extension class: {namespace}.{name}")
                exposed_names.add((namespace, name))
                exposed_base = rule.get("expose_base", "QObject")
                if exposed_base not in ("QObject", "QWidget"):
                    raise ValueError("expose_base must be QObject or QWidget")
                constructible = rule.get("constructible", False)
                if not isinstance(constructible, bool):
                    raise ValueError("constructible must be boolean")
                if excluded_method(
                    string_list_field(object_field(config, "exclude"), "members"), native, "new", []
                ):
                    constructible = False
                wrapper = (
                    f"QtTypedWidgetRef<{native}>"
                    if exposed_base == "QWidget"
                    else f"QtObjectRef<{native}>"
                )
                if functions and (constructible or exposed_base != "QObject"):
                    raise ValueError(
                        "Function bindings borrow a QObject; constructors and expose_base are unavailable"
                    )
                if functions and string_list_field(rule, "members", ["methods"]) != ["methods"]:
                    raise ValueError("Function bindings support methods only")
                if functions:
                    rule = dict(rule, members=["methods"])
                symbol = f"extension_{key}_{name}"
                context = string_list_field(rule, "context")
                object_parameter = (
                    (
                        f", {native} *object"
                        + "".join(f", {typ} context{i}" for i, typ in enumerate(context))
                    )
                    if functions
                    else ""
                )

                declarations.extend(
                    [
                        f"void register_{symbol}(lua_State *L{object_parameter});",
                        f"void pushExtensionObject(lua_State *L, {native} *object, bool owned = false);",
                    ]
                )
                native_include = f"#include {json.dumps(header.as_posix(), ensure_ascii=False)}"
                if native_include not in declarations:
                    declarations.insert(1, native_include)
                if not functions:
                    registrations.append(f"register_{symbol}(L);")
                cpp = [
                    '#include "qtluau/bindings.hpp"',
                    '#include "qtluau/widget_wrappers.hpp"',
                    '#include "qtluau/value_conversion.hpp"',
                    '#include "qtluau/object_ref.hpp"',
                    "#include <QMetaMethod>",
                    '#include "qtluau/access.hpp"',
                    f"#include {json.dumps(header.as_posix(), ensure_ascii=False)}",
                    "namespace qtluau {",
                    f"void register_{symbol}(lua_State *L{object_parameter}) {{",
                ]
                registrar = (
                    f'luabridge::getGlobalNamespace(L).beginNamespace("{namespace}")'
                    if namespace
                    else "luabridge::getGlobalNamespace(L)"
                )
                if functions:
                    cpp.append(
                        'if (!object) throw std::invalid_argument("Binding object is null");'
                    )
                    cpp.extend(
                        f'if (!context{i}) throw std::invalid_argument("Binding context is null");'
                        for i in range(len(context))
                    )
                    cpp.append(f"auto cls = {registrar};")
                elif exposed_base == "QWidget":
                    cpp.append(
                        f'static_assert(std::is_base_of_v<QWidget, {native}>, "expose_base requires a QWidget subclass");'
                    )
                    cpp.append(
                        f'auto cls = {registrar}.deriveClass<{wrapper}, QtWidgetRef>("{name}");'
                    )
                else:
                    cpp.append(
                        f'static_assert(std::is_base_of_v<QObject, {native}>, "QObject extension required");'
                    )
                    cpp.append(f'auto cls = {registrar}.beginClass<{wrapper}>("{name}");')
                if constructible:
                    cpp.append(
                        f'static_assert(std::is_default_constructible_v<{native}>, "constructible requires a public default constructor");'
                    )
                    cpp.append("cls.addConstructor<void (*)(), void (*)()>();")
                member_code, access_code, methods, properties = render_members(
                    native,
                    wrapper,
                    record,
                    rule,
                    native_members[native],
                    string_list_field(object_field(config, "exclude"), "members"),
                    "Access_" + symbol,
                )
                if functions and not methods:
                    raise ValueError(
                        f"No methods selected for function binding: {namespace}.{name}"
                    )
                # Access helpers live at namespace scope before registration functions.
                function_start = cpp.index(
                    f"void register_{symbol}(lua_State *L{object_parameter}) {{"
                )
                cpp[function_start:function_start] = access_code
                cpp.extend(member_code)
                cpp.extend(
                    [
                        ("cls.endNamespace();" if namespace else "(void)cls;")
                        if functions
                        else "qtluau::guardClassMethods(L, cls); cls.endClass();",
                        "}",
                        f"void pushExtensionObject(lua_State *L, {native} *object, bool owned) {{",
                        "if (!object) { lua_pushnil(L); return; }",
                        f"auto result = luabridge::Stack<{wrapper}>::push(L, {wrapper}(object, owned));",
                        "if (!result) throw std::runtime_error(result.message());",
                        "}",
                        "}",
                    ]
                )
                filename = f"qt_ext_{key}_{name}.cpp"
                if functions:
                    push_start = next(
                        i
                        for i, line in enumerate(cpp)
                        if line.startswith("void pushExtensionObject(")
                    )
                    cpp[push_start:] = ["}"]
                    declarations.remove(
                        f"void pushExtensionObject(lua_State *L, {native} *object, bool owned = false);"
                    )
                write(out / filename, "\n".join(cpp) + "\n")
                generated.add(filename)
                metadata.append(
                    {
                        "namespace": namespace,
                        "module": module,
                        "binding": "functions" if functions else "class",
                        "context": context,
                        "name": name,
                        "native": native,
                        "base": exposed_base,
                        "constructible": constructible,
                        "methods": methods,
                        "properties": properties,
                        "register": f"register_{symbol}",
                        "push": "pushExtensionObject",
                    }
                )
        missing = set(rules) - seen_classes
        if missing:
            raise ValueError(f"Extension classes absent from moc metadata: {sorted(missing)}")
    declarations.extend(
        [
            f"inline void registerGeneratedExtensions_{manifest_id}(lua_State *L) {{",
            "(void)L;",
            *registrations,
            "}",
            "}",
        ]
    )
    declarations.append(
        f"#define QTLUAU_REGISTER_EXTENSIONS(L) qtluau::registerGeneratedExtensions_{manifest_id}(L)"
    )
    write(out / "qt_extensions.hpp", "\n".join(declarations) + "\n")
    for stale in out.glob("qt_ext_*.cpp"):
        if stale.name not in generated:
            stale.unlink()
    for filename, values in [
        ("extension_inputs.txt", inputs),
        ("extension_globs.txt", input_patterns),
        ("extension_sources.txt", sources),
        ("extension_include_dirs.txt", include_dirs),
        ("extension_defines.txt", defines),
    ]:
        if any("\n" in str(value) or ";" in str(value) for value in values):
            raise ValueError("Extension paths/defines may not contain newlines or semicolons")
        write(out / filename, "".join(str(value) + "\n" for value in sorted(values)))
    return metadata


def definitions(entries: list[JsonObject]) -> str:
    """Render Luau declarations from resolved extension metadata."""
    lines: list[str] = []
    namespaces: dict[str, list[str]] = {}
    for entry in entries:
        namespace: str = entry["namespace"]
        name: str = entry["name"]
        if entry.get("binding") == "custom":
            continue
        if entry.get("binding") == "enum":
            values = object_field(entry, "values")
            namespaces.setdefault(namespace, []).append(
                f"    {name}: {{" + ", ".join(f"{key}: number" for key in values) + "},"
            )
            continue
        if entry.get("binding") in {"functions", "callbacks"}:
            groups: dict[str, list[str]] = {}
            for method in object_list_field(entry, "methods"):
                params = ", ".join(
                    f"arg{i}: {t}" for i, t in enumerate(string_list_field(method, "parameters"))
                )
                groups.setdefault(method["name"], []).append(f"(({params}) -> {method['result']})")
            namespaces.setdefault(namespace, []).extend(
                f"    {method}: {' & '.join(overloads)}," for method, overloads in groups.items()
            )
            continue
        alias = f"_ext_{namespace}_{name}"
        base = " extends _qt_QWidget" if entry["base"] == "QWidget" else ""
        lines.append(f"declare extern type {alias}{base} with")
        groups: dict[str, list[str]] = {}
        for method in object_list_field(entry, "methods"):
            params = ", ".join(
                f"arg{i}: {t}" for i, t in enumerate(string_list_field(method, "parameters"))
            )
            groups.setdefault(method["name"], []).append(
                f"((self: {alias}{', ' if params else ''}{params}) -> {method['result']})"
            )
        for method, overloads in groups.items():
            lines.append(f"    {method}: " + " & ".join(overloads))
        for prop in object_list_field(entry, "properties"):
            field = str(prop["name"])
            if field in KEYWORDS:
                field = "[" + json.dumps(field) + "]"
            lines.append(f"    {field}: {prop['type']}")
        lines.append("end")
        constructor = f"(() -> {alias})" if entry["constructible"] else "{}"
        namespaces.setdefault(namespace, []).append(f"    {name}: {constructor},")
    for namespace, fields in namespaces.items():
        if namespace:
            lines.extend([f"declare {namespace}: {{", *fields, "}"])
        else:
            lines.extend("declare " + field.strip().rstrip(",") for field in fields)
    return "\n".join(lines) + "\n"
