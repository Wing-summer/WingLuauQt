# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate a standalone static binding library and deployable module definitions."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys

from .assets import support_root
from .callback_bindings import emit_callbacks
from .extensions import identifier, paths, write
from .extra_bindings import extra_bindings
from .function_naming import apply_function_naming
from .generate_definitions import generate
from .header_guards import guard_headers
from .models import JsonObject, object_field, object_list_field, string_list_field
from .module_definitions import module_definitions
from .native_apis import emit_native_apis
from .qt_pipeline import emit
from .sdk_version import validate_version


def cpp_name(value: object) -> str:
    """Validate a public C++ name and reject reserved language keywords."""
    name = identifier(value)
    if name in {"class", "namespace", "struct", "template", "public", "private", "protected"}:
        raise ValueError(f"Invalid C++ identifier: {name}")
    return name


def quote(value: pathlib.Path | str) -> str:
    # CMake bracket arguments preserve spaces and prevent variable expansion.
    """Quote a CMake path without expansion, rejecting ambiguous delimiters."""
    text = str(value).replace("\\", "/")
    if "]=]" in text or "\n" in text or ";" in text:
        raise ValueError("Unsupported newline, semicolon or bracket delimiter in path")
    return "[=[" + text + "]=]"


def copy_native(
    config: JsonObject, base: pathlib.Path, output: pathlib.Path
) -> tuple[dict[str, str], list[str], list[str], list[str]]:
    """Copy configured native inputs and return relocation maps and build inputs."""
    files: set[pathlib.Path] = set()
    sources: set[pathlib.Path] = set()
    directories: set[pathlib.Path] = set()
    defines: set[str] = set()
    for entry in object_list_field(config, "extensions"):
        headers = paths(base, string_list_field(entry, "headers"))
        native_sources = paths(base, string_list_field(entry, "sources"))
        files.update(headers)
        files.update(native_sources)
        sources.update(native_sources)
        directories.update(paths(base, string_list_field(entry, "include_dirs")))
        defines.update(string_list_field(entry, "defines"))
        # Copy sibling headers used by declarations without copying build trees.
        for directory in {p.parent for p in [*headers, *native_sources]}:
            files.update(
                p
                for p in directory.iterdir()
                if p.is_file() and p.suffix in {".h", ".hpp", ".hxx", ".inc"}
            )
    for directory in directories:
        files.update(
            p
            for p in directory.rglob("*")
            if p.is_file() and p.suffix in {".h", ".hpp", ".hxx", ".inc"}
        )
    pending = list(files)
    # Preserve relative quoted includes (including ../common.hpp) without copying
    # unrelated build/dependency trees beneath the application source directory.
    while pending:
        source = pending.pop()
        text = source.read_text(errors="replace")
        for include in re.findall(r'^\s*#\s*include\s*"([^"\n]+)"', text, re.MULTILINE):
            for directory in [source.parent, *sorted(directories)]:
                candidate = (directory / include).resolve()
                if candidate.is_file():
                    if candidate not in files:
                        files.add(candidate)
                        pending.append(candidate)
                    break
    if not files:
        return {}, [], [], sorted(defines)
    common = pathlib.Path(os.path.commonpath([*(p.parent for p in files), *directories]))
    replacements: dict[str, str] = {}
    for source in sorted(files):
        relative = pathlib.Path("native") / source.relative_to(common)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        replacements[str(source)] = relative.as_posix()
        replacements[source.as_posix()] = relative.as_posix()
    include_dirs = [
        "native",
        *(str(pathlib.Path("native") / d.relative_to(common)) for d in sorted(directories)),
    ]
    return (
        replacements,
        [replacements[str(s)] for s in sorted(sources)],
        include_dirs,
        sorted(defines),
    )


def generation_inputs(config: JsonObject, output: pathlib.Path, base: pathlib.Path) -> None:
    """Write relocatable CMake watchers for configured native input patterns.

    Args:
        config: Binding policy with source, header and paired definition inputs.
        output: Generated project root receiving the CMake watcher sidecar.
        base: Source root used to normalize explicitly absolute local inputs.

    Raises:
        ValueError: An input path contains unsupported CMake delimiters.
    """
    patterns: set[str] = set()
    for group, fields in (("extensions", ("headers", "sources")),
                          ("native_apis", ("headers",)),
                          ("extra_bindings", ("files", "definitions"))):
        for entry in object_list_field(config, group):
            for field in fields:
                for spelling in string_list_field(entry, field):
                    if spelling.startswith("@qtluau/"):
                        continue
                    path = pathlib.Path(spelling)
                    if path.is_absolute() and path.is_relative_to(base.resolve()):
                        path = path.relative_to(base.resolve())
                    pattern = path.as_posix()
                    if any(char in pattern for char in '\n\r;"$'):
                        raise ValueError("Unsupported CMake input path delimiter")
                    patterns.add(pattern if path.is_absolute() else "${_wingluauqt_input_root}/" + pattern)
    lines = ["# Generated source-input watchers; the generation driver supplies the root."]
    for index, pattern in enumerate(sorted(patterns)):
        lines.append(f'file(GLOB_RECURSE _wingluauqt_input_{index} CONFIGURE_DEPENDS "{pattern}")')
        lines.append(f'set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${{_wingluauqt_input_{index}}})')
    write(output / "generation_inputs.cmake", "\n".join(lines) + "\n")


def module_symbol(module: str) -> str:
    """Return the public registration function name for a module key."""
    return "registerModule_" + module if module else "registerPublicModule"


def snapshot_outputs(output: pathlib.Path) -> dict[pathlib.Path, tuple[bytes, int, int]]:
    """Remember generated content and timestamps to avoid redundant recompilation.

    Only generator-owned source directories and root files are traversed;
    dependency checkouts, version control metadata and build trees are excluded.
    """
    if not output.exists():
        return {}
    root_names = {"CMakeLists.txt", "README.md", "LICENSE", "manifest.json", "binding_policy.json", "generation_inputs.cmake"}
    files = [path for path in output.iterdir() if path.is_file() and (path.name in root_names or path.suffix == ".qrc")]
    for directory in ("generated", "include", "support", "modules", "native", "definitions"):
        files.extend(path for path in (output / directory).rglob("*") if path.is_file())
    result: dict[pathlib.Path, tuple[bytes, int, int]] = {}
    for path in files:
        if ".git" in path.relative_to(output).parts:
            continue
        stat = path.stat()
        result[path] = (path.read_bytes(), stat.st_atime_ns, stat.st_mtime_ns)
    return result


def restore_unchanged_outputs(previous: dict[pathlib.Path, tuple[bytes, int, int]]) -> None:
    """Keep timestamps for files whose final generated contents did not change."""
    for path, (content, accessed, modified) in previous.items():
        if path.is_file() and path.read_bytes() == content:
            os.utime(path, ns=(accessed, modified))


def export_project(config: JsonObject, output: pathlib.Path, base: pathlib.Path) -> JsonObject:
    """Export a static library from validated policy and host-relative inputs.

    Args:
        config: Binding policy, module descriptors and project options.
        output: Destination root for the independently buildable library.
        base: Host root used to resolve configured input paths.

    Returns:
        Manifest containing deployed module paths and native callback contracts.

    Raises:
        ValueError: Policy, discovery or a generated name is invalid.
    """
    if "packages" in config:
        raise ValueError("packages is no longer supported; configure application modules through extra_bindings")
    root = support_root()
    validate_version(config)
    policy = object_field(config, "project")
    if set(policy) - {"name", "namespace", "native_mode", "host_targets", "definitions_directory", "helpers"}:
        raise ValueError("Unknown project option")
    helpers = set(string_list_field(policy, "helpers"))
    if helpers - {"execution", "require"}:
        raise ValueError("project.helpers accepts only execution and require")
    execution_helper = "execution" in helpers
    require_helper = "require" in helpers
    definition_directory = policy.get("definitions_directory", "luaudef")
    if not isinstance(definition_directory, str) or not definition_directory or any(c in definition_directory for c in '\n\r;"'):
        raise ValueError("project.definitions_directory must be a nonempty filesystem path")
    name = cpp_name(policy.get("name", "GeneratedBindings"))
    namespace = cpp_name(policy.get("namespace", "generated_bindings"))
    output = output.resolve()
    source_root = base.resolve()
    maintained_roots = (root / directory for directory in (
        "python", "include", "support", "cmake", "config", "examples", "tests", "docs"
    ))
    if root.is_relative_to(output) or source_root.is_relative_to(output) or any(
        output.is_relative_to(directory) for directory in maintained_roots
    ):
        raise ValueError("Output must be separate from framework and native source roots")
    for group, fields in (("extensions", ("headers", "sources")),
                          ("native_apis", ("headers",)),
                          ("extra_bindings", ("files", "definitions"))):
        for entry in object_list_field(config, group):
            for field in fields:
                for pattern in string_list_field(entry, field):
                    if not pattern.startswith("@qtluau/"):
                        if any(path.is_file() and path.is_relative_to(output) for path in paths(base, [pattern])):
                            raise ValueError("Output must not contain maintained native input files")
    previous_outputs = snapshot_outputs(output)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "LICENSE", output / "LICENSE")
    generated = output / "generated"
    resolved = emit(config, generated, base)
    definitions_dir = output / "definitions"
    generate(resolved, definitions_dir)
    metadata = object_list_field(resolved, "_extensions")
    metadata.extend(emit_native_apis(config, generated, base))
    extra_metadata, extra_definitions = extra_bindings(config, generated, base)
    for module, source in emit_callbacks(config, generated).items():
        extra_definitions[module] = extra_definitions.get(module, "") + source
    metadata.extend(extra_metadata)
    public_modules = {"qt"} | {
        str(entry["module"]) for entry in metadata
        if entry.get("module") and entry.get("binding") != "custom"
    }
    module_text = module_definitions(definitions_dir, metadata, extra_definitions, public_modules)
    modules = sorted(module_text)
    symbols = [module_symbol(m) for m in modules]
    if len(set(symbols)) != len(symbols):
        raise ValueError("Module names collide with the generated public registration symbol")
    for directory in ("include", "support"):
        shutil.copytree(
            root / directory,
            output / directory,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("CMakeLists.txt"),
        )
    for helper, files in (
        (execution_helper, ("support/execute_luau.cpp", "include/qtluau/execution.hpp")),
        (require_helper, ("support/module_registry.cpp", "include/qtluau/module_require.hpp")),
    ):
        if not helper:
            for filename in files:
                (output / filename).unlink(missing_ok=True)
    # Registration sources are generator inputs, not an additional adapter library.
    shutil.rmtree(generated / "registrations", ignore_errors=True)
    shutil.rmtree(generated / "packages", ignore_errors=True)
    shutil.rmtree(output / "adapters", ignore_errors=True)
    native_mode = policy.get("native_mode", "copy")
    if native_mode not in {"copy", "reference"}:
        raise ValueError("native_mode must be copy or reference")
    host_targets = string_list_field(policy, "host_targets")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_:.-]*", target) for target in host_targets):
        raise ValueError("Invalid host target name")
    if native_mode == "copy":
        replacements, native_sources, include_dirs, defines = copy_native(config, base, output)
    else:
        replacements: dict[str, str] = {}
        include_dirs: list[str] = []
        defines: list[str] = []
        native_sources: list[str] = []
        for entry in object_list_field(config, "extensions"):
            if string_list_field(entry, "sources") or entry.get("compile_moc", True):
                raise ValueError("reference mode requires compile_moc=false and host-owned sources")
            for header in paths(base, string_list_field(entry, "headers")):
                if not header.is_relative_to(base.resolve()):
                    raise ValueError("Referenced headers must be below the configuration directory")
                replacements[str(header)] = header.relative_to(base.resolve()).as_posix()
            include_dirs.extend(
                str(d.relative_to(base.resolve()))
                for d in paths(base, string_list_field(entry, "include_dirs"))
            )
            defines.extend(string_list_field(entry, "defines"))
        shutil.rmtree(output / "native", ignore_errors=True)
    for entry in object_list_field(config, "native_apis"):
        for header in paths(base, string_list_field(entry, "headers")):
            if native_mode != "reference" or not header.is_relative_to(base.resolve()):
                raise ValueError("native_apis requires host-relative headers and reference mode")
            replacements[str(header)] = header.relative_to(base.resolve()).as_posix()
    # Build native meta-objects with the consuming SDK, not the scanning SDK.
    moc_headers: set[str] = set()
    if native_mode == "copy":
        for entry in object_list_field(config, "extensions"):
            if entry.get("compile_moc", True):
                moc_headers.update(replacements[str(header)] for header in paths(base, string_list_field(entry, "headers")))
    for artifact in generated.glob("qt_ext_moc_*.cpp"):
        artifact.unlink()
    # Freeze generated includes to project-relative paths, allowing relocation.
    for path in generated.glob("*"):
        if path.suffix not in {".cpp", ".hpp"}:
            continue
        text = path.read_text()
        for original, relative in replacements.items():
            text = text.replace(original, relative)
        write(path, text)
    definition_paths: dict[str, str] = {}
    (output / f"{name}_definitions.qrc").unlink(missing_ok=True)
    (output / f"{name}_policy.qrc").unlink(missing_ok=True)
    (output / "binding_policy.json").unlink(missing_ok=True)
    (output / "support/qt/config.cpp").unlink(missing_ok=True)
    for filename in ("support/qt/widget_wrappers.cpp", "support/qt/qt_ui_loader.cpp", "support/qt/binding_config.cpp", "include/qtluau/config.hpp", "include/qtluau/string_values.hpp", "include/qtluau/constructor_registration.hpp"):
        (output / filename).unlink(missing_ok=True)
    for index, module in enumerate(modules):
        filename = f"module_{index}.d.luau"
        write(definitions_dir / filename, module_text[module])
        definition_paths[module] = f"{name}_{filename}"
    expected_definitions = {f"module_{index}.d.luau" for index in range(len(modules))}
    for artifact in definitions_dir.glob("*.d.luau"):
        if artifact.name not in expected_definitions:
            artifact.unlink()
    declarations = [
        "#pragma once",
        '#include "qtluau/bindings.hpp"',
        '#include "qtluau/packages.hpp"',
        '#include "qt_extensions.hpp"',
        '#include "native_apis.hpp"',
        '#include "callback_bindings.hpp"',
        "#include <QHash>",
        f"namespace {namespace} {{",
    ]
    declarations.extend(f"void {module_symbol(module)}(lua_State *L);" for module in modules)
    for entry in metadata:
        if entry.get("binding") == "callbacks":
            module = str(entry.get("module", ""))
            declarations.append(
                f"void bind_{module or 'public'}_{entry['name']}(lua_State *L, const {entry['callback_type']} &callbacks);"
            )
            continue
        if entry.get("binding") == "functions":
            declarations.append(
                f"void bind_{entry.get('module', entry['namespace']) or 'public'}_{entry['name']}(lua_State *L, {entry['native']} *object"
                + "".join(
                    f", {typ} context{i}"
                    for i, typ in enumerate(string_list_field(entry, "context"))
                )
                + ");"
            )
    declarations.extend(
        [
            "void registerModule(lua_State *L, QAnyStringView name);",
            f"void registerAllModules(lua_State *L, bool installRequire = {str(require_helper).lower()});",
            "QHash<QString, QString> definitionFiles();",
            "QHash<QString, QString> moduleFiles();",
            "}",
        ]
    )
    if execution_helper:
        declarations.insert(1, '#include "qtluau/execution.hpp"')
        declarations.insert(declarations.index("}"), "bool executeScript(lua_State *L, QAnyStringView source, QString *error = nullptr);")
    if require_helper:
        declarations.insert(1, '#include "qtluau/module_require.hpp"')
    declarations.extend(
        f'#include "custom/{path.name}"' for path in sorted((generated / "custom").glob("*.hpp"))
    )
    write(output / "include/generated_bindings.hpp", "\n".join(declarations) + "\n")
    common_call = "qtluau::registerCommonBindings(L);"
    qt_call = "qtluau::registerQtBindings(L);"
    cpp = [
        '#include "generated_bindings.hpp"',
        '#include "qt_extensions.hpp"',
        '#include "static_registration.hpp"',
        "#include <stdexcept>",
        f"namespace {namespace} {{",
        "namespace detail {",
        'bool done(lua_State *L, const char *key) { if (!L) throw std::invalid_argument("lua_State is null"); lua_getfield(L, LUA_REGISTRYINDEX, key); bool value = lua_toboolean(L, -1); lua_pop(L, 1); return value; }',
        "void mark(lua_State *L, const char *key) { lua_pushboolean(L, true); lua_setfield(L, LUA_REGISTRYINDEX, key); }",
        f'void common(lua_State *L) {{ const char *key="{name}.base.common"; if (done(L,key)) return; {common_call} mark(L,key); }}',
        f'void qtBase(lua_State *L) {{ const char *key="{name}.base.qt"; if (done(L,key)) return; common(L); {qt_call} mark(L,key); }}',
        "}",
    ]
    module_dir = output / "modules"
    module_dir.mkdir(exist_ok=True)
    generated_modules = {"support.cpp", "aggregate.cpp", "definitions.cpp"}
    private_header = [
        "#pragma once",
        '#include "qtluau/bindings.hpp"',
        f"namespace {namespace}::detail {{",
        "bool done(lua_State *L, const char *key);",
        "void mark(lua_State *L, const char *key);",
        "void common(lua_State *L);",
        "void qtBase(lua_State *L);",
        "}",
    ]
    private_header.extend(
        f"namespace qtluau {{ void {e['register']}(lua_State *L); }}" for e in extra_metadata
    )
    write(generated / "module_support.hpp", "\n".join(private_header) + "\n")
    cpp.insert(0, '#include "module_support.hpp"')
    write(module_dir / "support.cpp", "\n".join([*cpp, "}"]) + "\n")
    file_prefix = [
        '#include "generated_bindings.hpp"',
        '#include "module_support.hpp"',
        "#include <QDir>",
        "#include <QFile>",
        "#include <QFileInfo>",
        "#include <stdexcept>",
        f"namespace {namespace} {{",
    ]
    cpp = list(file_prefix)
    for module_index, module in enumerate(modules):
        chunk_start = len(cpp)
        entries = [e for e in metadata if e.get("module", e["namespace"]) == module]
        type_spellings = [
            str(typ)
            for entry in entries
            for method in object_list_field(entry, "methods")
            for typ in [method["result"], *string_list_field(method, "parameters")]
        ] + [
            str(prop["type"])
            for entry in entries
            for prop in object_list_field(entry, "properties")
        ]
        needs_qt = (
            module == "qt"
            or any(e["base"] == "QWidget" for e in entries)
            or any(
                "_qt_" in spelling or re.search(r"\bany\b", spelling) for spelling in type_spellings
            )
        )
        key = name + ".module." + module
        cpp.extend(
            [
                f"void {module_symbol(module)}(lua_State *L) {{",
                f'const char *key = "{key}"; if (done(L,key)) return;',
                "common(L);",
            ]
        )
        if module:
            cpp.append(module_symbol("") + "(L);")
        if needs_qt:
            cpp.append("qtBase(L);")
        cpp.extend(
            "qtluau::" + str(e["register"]) + "(L);"
            for e in entries
            if e.get("binding") not in {"functions", "callbacks"}
        )
        if (
            module
            and (module == "qt" or any(e.get("binding") != "custom" for e in entries))
        ):
            cpp.extend(
                [
                    f'lua_getglobal(L, "{module}");',
                    f'qtluau::rememberModule(L, "{module}", -1);',
                    "lua_pop(L, 1);",
                ]
            )
        cpp.extend(["mark(L,key);", "}"])
        for entry in entries:
            if entry.get("binding") == "callbacks":
                cpp.append(
                    f"void bind_{module or 'public'}_{entry['name']}(lua_State *L, const {entry['callback_type']} &callbacks) {{ {module_symbol(module)}(L); qtluau::{entry['register']}(L, callbacks); }}"
                )
                continue
            if entry.get("binding") == "functions":
                context_types = string_list_field(entry, "context")
                context_parameters = "".join(
                    f", {typ} context{i}" for i, typ in enumerate(context_types)
                )
                context_arguments = "".join(f", context{i}" for i in range(len(context_types)))
                cpp.append(
                    f"void bind_{module or 'public'}_{entry['name']}(lua_State *L, {entry['native']} *object{context_parameters}) {{ {module_symbol(module)}(L); qtluau::{entry['register']}(L, object{context_arguments}); }}"
                )
        filename = f"module_{module_index}_{module or 'public'}.cpp"
        generated_modules.add(filename)
        write(
            module_dir / filename,
            "\n".join([*file_prefix, "using namespace detail;", *cpp[chunk_start:], "}"]) + "\n",
        )
        del cpp[chunk_start:]

    cpp.append("void registerModule(lua_State *L, QAnyStringView name) {")
    for module in modules:
        cpp.append(
            f'if (name == QAnyStringView("{module}")) {{ {module_symbol(module)}(L); return; }}'
        )
    cpp.extend(
        [
            'throw std::invalid_argument("Unknown binding module");',
            "}",
            "void registerAllModules(lua_State *L, bool installRequire) {",
        ]
    )
    if not require_helper:
        cpp.append('if (installRequire) { throw std::invalid_argument("The require helper is not enabled in project.helpers"); }')
    cpp.extend(module_symbol(module) + "(L);" for module in modules)
    if require_helper:
        cpp.append("if (installRequire) { qtluau::installModuleRequire(L); }")
    cpp.append("}")
    write(module_dir / "aggregate.cpp", "\n".join([*cpp, "}"]) + "\n")
    cpp = ["#include <QCoreApplication>", *file_prefix]
    for function, selected in (("definitionFiles", {"": definition_paths[""]}),
                               ("moduleFiles", {key: value for key, value in definition_paths.items() if key})):
        cpp.extend([
            f"QHash<QString, QString> {function}() {{",
            "const QDir directory(QDir(QCoreApplication::applicationDirPath()).absoluteFilePath(QStringLiteral(QTLUAU_DEFINITION_DIRECTORY)));",
            "return {",
        ])
        cpp.extend(f'{{QStringLiteral("{module}"), directory.absoluteFilePath(QStringLiteral("{path}"))}},' for module, path in selected.items())
        cpp.extend(["};", "}"])
    if execution_helper:
        cpp.append("bool executeScript(lua_State *L, QAnyStringView source, QString *error) { return qtluau::executeLuau(L, source, error); }")
    cpp.append("}")
    write(module_dir / "definitions.cpp", "\n".join(cpp) + "\n")
    for stale in module_dir.glob("*.cpp"):
        if stale.name not in generated_modules:
            stale.unlink()
    (output / "modules.cpp").unlink(missing_ok=True)
    source_patterns = [
        '"${CMAKE_CURRENT_SOURCE_DIR}/generated/*.cpp"',
        '"${CMAKE_CURRENT_SOURCE_DIR}/modules/*.cpp"',
        '"${CMAKE_CURRENT_SOURCE_DIR}/generated/registrations/*.cpp"',
        '"${CMAKE_CURRENT_SOURCE_DIR}/generated/custom/*.cpp"',
        '"${CMAKE_CURRENT_SOURCE_DIR}/support/qt/*.cpp"',
        '"${CMAKE_CURRENT_SOURCE_DIR}/support/*.cpp"',
    ]
    native_source_lines = "\n".join("  " + quote(s) for s in [*native_sources, *sorted(moc_headers)])
    include_lines = "\n".join("  " + quote(d) for d in ["include", ".", *include_dirs])
    if native_mode == "reference":
        include_lines = "\n".join(
            [
                "  [=[include]=]",
                "  [=[.]=]",
                f'  "${{{name}_HOST_SOURCE_DIR}}"',
                *[f'  "${{{name}_HOST_SOURCE_DIR}}/{d}"' for d in include_dirs],
            ]
        )
    for native_api in object_list_field(config, "native_apis"):
        include_lines += "\n" + "\n".join(
            f'  "${{{name}_HOST_SOURCE_DIR}}/{p.relative_to(base.resolve()).as_posix()}"'
            if native_mode == "reference"
            else "  " + quote(p)
            for p in paths(base, string_list_field(native_api, "include_dirs"))
        )
    host_root = (
        f'set({name}_HOST_SOURCE_DIR "${{CMAKE_SOURCE_DIR}}" CACHE PATH "Host source root containing binding configuration")'
        if native_mode == "reference"
        else ""
    )
    host_checks = "\n".join(
        f'if(NOT TARGET {target})\n  message(FATAL_ERROR "Required host target {target} must exist before adding {name}")\nendif()'
        for target in host_targets
    )
    cmake = f"""cmake_minimum_required(VERSION 3.24)
project({name} LANGUAGES CXX)
# Preserve the parent AUTOMOC policy; native input headers enable it per target.
set(CMAKE_AUTOMOC OFF)
{host_root}
{host_checks}
find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets UiTools)
find_package(Threads REQUIRED)
set(LUAU_SOURCE_DIR "${{CMAKE_SOURCE_DIR}}/3rdparty/luau" CACHE PATH "Luau source dependency")
set(LUABRIDGE3_SOURCE_DIR "${{CMAKE_SOURCE_DIR}}/3rdparty/LuaBridge3" CACHE PATH "LuaBridge3 source dependency")
if(NOT TARGET Luau.VM)
  set(LUAU_BUILD_CLI OFF CACHE BOOL "" FORCE)
  set(LUAU_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  add_subdirectory("${{LUAU_SOURCE_DIR}}" "${{CMAKE_CURRENT_BINARY_DIR}}/luau" EXCLUDE_FROM_ALL)
endif()
find_path(LUABRIDGE3_INCLUDE_DIR LuaBridge/LuaBridge.h HINTS "${{LUABRIDGE3_SOURCE_DIR}}/Source" REQUIRED)
file(GLOB binding_sources CONFIGURE_DEPENDS {" ".join(source_patterns)})
add_library({name} STATIC ${{binding_sources}}
{native_source_lines}
)
add_library({name}::Bindings ALIAS {name})
set_target_properties({name} PROPERTIES AUTOMOC ON)
target_compile_features({name} PUBLIC cxx_std_17)
target_include_directories({name} PUBLIC
{include_lines}
  "${{LUABRIDGE3_INCLUDE_DIR}}"
  "${{CMAKE_CURRENT_SOURCE_DIR}}/generated")
target_compile_definitions({name} PUBLIC {" ".join(quote(d) for d in defines)})
target_link_libraries({name} PUBLIC Qt6::Core Qt6::Gui Qt6::Widgets Qt6::UiTools Luau.VM {"Luau.Compiler " if execution_helper else ""}Threads::Threads {" ".join(host_targets)})
"""
    filenames = " ".join(quote(f"module_{i}.d.luau") for i in range(len(modules)))
    cmake += f"""
set({name}_DEFINITIONS_DIR {quote(definition_directory)} CACHE STRING "Definition directory relative to the executable, or an absolute path")
target_compile_definitions({name} PRIVATE "QTLUAU_DEFINITION_DIRECTORY=\\\"${{{name}_DEFINITIONS_DIR}}\\\"")
set_property(TARGET {name} PROPERTY QTLUAU_DEFINITION_SOURCES "${{CMAKE_CURRENT_SOURCE_DIR}}/definitions")
function({name}_copy_definitions target)
  if(TARGET {name}_${{target}}_definitions)
    return()
  endif()
  get_target_property(_sources {name} QTLUAU_DEFINITION_SOURCES)
  if(IS_ABSOLUTE "${{{name}_DEFINITIONS_DIR}}")
    set(_destination "${{{name}_DEFINITIONS_DIR}}")
  else()
    set(_destination "$<TARGET_FILE_DIR:${{target}}>/${{{name}_DEFINITIONS_DIR}}")
  endif()
  add_custom_target({name}_${{target}}_definitions ALL COMMAND "${{CMAKE_COMMAND}}" -E make_directory "${{_destination}}")
  foreach(_file IN ITEMS {filenames})
    add_custom_command(TARGET {name}_${{target}}_definitions POST_BUILD
      COMMAND "${{CMAKE_COMMAND}}" -E copy_if_different "${{_sources}}/${{_file}}" "${{_destination}}/{name}_${{_file}}"
      VERBATIM)
  endforeach()
  add_dependencies(${{target}} {name}_${{target}}_definitions)
endfunction()
"""
    write(output / "CMakeLists.txt", cmake)
    manifest: JsonObject = {
        "name": name,
        "namespace": namespace,
        "modules": definition_paths,
        "native_sources": native_sources,
        "native_mode": native_mode,
        "helpers": sorted(helpers),
        "host_targets": host_targets,
        "native_bindings": [entry for entry in metadata if entry.get("binding") == "callbacks"],
    }
    write(output / "manifest.json", json.dumps(manifest, indent=2) + "\n")
    write(
        output / "README.md",
        f"# {name}\n\nGenerated standalone static CMake library. Link `{name}::Bindings` and include `generated_bindings.hpp`.\n\nCall `registerPublicModule`, `registerModule_qt`, a configured module function, or `registerAllModules`. `definitionFiles()` returns the shared global definition; `moduleFiles()` returns named module type entry paths. Load the shared definition once and let the host resolve module type entry files. Call `{name}_copy_definitions(YourExecutable)` in CMake; configure `{name}_DEFINITIONS_DIR` (default `luaudef`) to change the location. {"`executeScript` compiles and runs Luau source. " if execution_helper else ""}{"The optional require wrapper is available. " if require_helper else "The host owns require. "} Dependencies are Qt 6, Luau and LuaBridge3; override their CMake source paths when relocating.\n",
    )
    # Disposable parser/moc reports are useful in development scan output, but
    # have no role in the library repository delivered to the host.
    for artifact in generated.iterdir():
        if artifact.is_file() and artifact.suffix in {".json", ".txt", ".yml", ".luau"}:
            artifact.unlink()
    (generated / "qt_scan.hpp").unlink(missing_ok=True)
    # Catalog defaults and JSON fixture discovery belong only to the harness.
    for filename in (
        "common_types.inc", "default_widgets.inc", "excluded_classes.inc",
        "default_excluded_members.inc", "qt_selected.inc",
    ):
        (generated / filename).unlink(missing_ok=True)
    generation_inputs(config, output, base)
    apply_function_naming(config, output)
    guard_headers(output, name)
    restore_unchanged_outputs(previous_outputs)
    return manifest


def main() -> int:
    """Parse export paths, generate the static project and return an exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--root", type=pathlib.Path, help="Root for relative native input paths")
    args = parser.parse_args()
    try:
        config: JsonObject = json.loads(args.config.read_text())
        manifest = export_project(config, args.out, (args.root or args.config.resolve().parent).resolve())
        print(f"Generated {manifest['name']} in {args.out.resolve()}")
    except (OSError, ValueError, KeyError) as error:
        print(f"Project generation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
