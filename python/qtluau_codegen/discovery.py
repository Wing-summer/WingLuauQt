# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Qt SDK discovery through tsujikiri's public IR parser."""

from __future__ import annotations

import functools
import importlib
import pathlib
import re
import shlex
import shutil
import subprocess
from typing import cast

from .models import NativeClass, NativeMethod

# Enum declarations discovered alongside native classes, keyed by qualified type.
SDK_ENUMS: dict[str, dict[str, int]] = {}
#: Fully resolved QFlags aliases, discovered from compiler typedef declarations.
SDK_FLAGS: dict[str, str] = {}


def command(args: list[str]) -> str:
    """Run an SDK query command and return stripped standard output."""
    return subprocess.check_output(args, text=True).strip()


def discover_sdk(modules: list[str]) -> list[str]:
    """Locate Qt modules and compiler flags, rejecting unavailable SDK inputs."""
    for module in modules:
        if not re.fullmatch(r"Qt[A-Za-z0-9]+", module):
            raise ValueError(f"invalid Qt module: {module}")
    if shutil.which("pkg-config"):
        result = subprocess.run(
            ["pkg-config", "--cflags", *["Qt6" + m[2:] for m in modules]],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return shlex.split(result.stdout)
    for name in ("qtpaths6", "qtpaths", "qmake6", "qmake"):
        if shutil.which(name):
            root = pathlib.Path(
                command(
                    [
                        name,
                        "--query" if "qtpaths" in name else "-query",
                        "QT_INSTALL_HEADERS",
                    ]
                )
            )
            if all((root / m).is_dir() for m in modules):
                return [f"-I{root}", *[f"-I{root / m}" for m in modules]]
    raise ValueError(
        "Qt6 SDK not found via pkg-config, qtpaths or qmake; configure the SDK environment first"
    )


def scan(modules: list[str]) -> tuple[dict[str, NativeClass], list[str]]:
    """Return SDK records cached within this generation process."""
    return _scan(tuple(modules))


@functools.cache
def _scan(modules: tuple[str, ...]) -> tuple[dict[str, NativeClass], list[str]]:
    """Use tsujikiri IR and retain public constructor default-argument arities."""
    import tempfile

    from tsujikiri.configurations import SourceConfig
    from tsujikiri.ir import IRClass, IRMethod
    from tsujikiri.parser import parse_translation_unit_ir

    from .member_scan import Clang

    flags = discover_sdk(list(modules))
    if shutil.which("clang++"):
        flags.append("-resource-dir=" + command(["clang++", "-print-resource-dir"]))
    with tempfile.TemporaryDirectory(prefix="qtluau-sdk-") as temporary:
        source = pathlib.Path(temporary) / "qt_scan.hpp"
        source.write_text("\n".join(f"#include <{m}/{m}>" for m in modules))
        errors: list[str] = []
        module = parse_translation_unit_ir(
            SourceConfig(path=str(source), parse_args=["-std=c++17", *flags]),
            [],
            "qt",
            clang_errors=errors,
        )
        if errors:
            raise ValueError("tsujikiri could not parse the Qt SDK:\n" + "\n".join(errors))
        # Semantic deletion survives Qt macros whose token spelling is not '= delete'.
        clang = cast(Clang, importlib.import_module("clang.cindex"))
        unit = clang.Index.create().parse(str(source), args=["-std=c++17", *flags])
        deleted: dict[str, set[tuple[str, ...]]] = {}
        noncopyable: set[str] = set()
        constructor_cursors = (
            child
            for record in unit.cursor.get_children()
            if (
                record.kind.name in {"CLASS_DECL", "STRUCT_DECL"}
                and re.fullmatch(r"Q[A-Za-z0-9_]+", record.spelling)
            )
            or (record.kind.name == "NAMESPACE" and record.spelling == "Qt")
            for child in record.get_children()
        )
        for cursor in constructor_cursors:
            if cursor.kind.name in {"TYPEDEF_DECL", "TYPE_ALIAS_DECL"}:
                canonical = cursor.underlying_typedef_type.get_canonical().spelling
                parent = cursor.semantic_parent
                if canonical.startswith("QFlags<") and parent is not None:
                    SDK_FLAGS[parent.spelling + "::" + cursor.spelling] = canonical
                continue
            if cursor.kind.name != "CONSTRUCTOR" or not cursor.is_deleted_method():
                continue
            parent = cursor.semantic_parent
            if parent is None:
                continue
            owner = parent.spelling
            deleted.setdefault(owner, set()).add(
                tuple(re.sub(r"\s+", "", arg.type.spelling) for arg in cursor.get_arguments())
            )
            if cursor.is_copy_constructor():
                noncopyable.add(owner)

    for enum in [*module.enums, *(enum for record in module.classes for enum in record.enums)]:
        if not enum.is_anonymous:
            SDK_ENUMS[enum.qualified_name] = {value.name: value.value for value in enum.values}
    for record in module.classes:
        for enum in record.enums:
            if enum.is_anonymous:
                SDK_ENUMS.setdefault(record.qualified_name + "::", {}).update(
                    {value.name: value.value for value in enum.values}
                )
    candidates: dict[str, IRClass] = {
        c.name: c
        for c in module.classes
        if c.source_file
        and c.name == c.qualified_name
        and re.fullmatch(r"Q[A-Za-z0-9_]+", c.name)
        and any("/" + m + "/" in c.source_file.replace("\\", "/") for m in modules)
    }

    def signature(method: IRMethod) -> tuple[str, tuple[str, ...], bool]:
        """Build a stable signature key for a native method."""
        return (
            method.name,
            tuple(p.type_spelling for p in method.parameters),
            method.is_const,
        )

    def abstract_methods(
        name: str, seen: set[str] | None = None
    ) -> set[tuple[str, tuple[str, ...], bool]]:
        """Collect unresolved pure virtual methods for abstract-class filtering."""
        seen = set() if seen is None else seen
        if name in seen or name not in candidates:
            return set()
        seen.add(name)
        record = candidates[name]
        pending = {s for base in record.bases for s in abstract_methods(base.qualified_name, seen)}
        for method in record.methods:
            if method.is_pure_virtual:
                pending.add(signature(method))
            else:
                pending.discard(signature(method))
        return pending

    classes: dict[str, NativeClass] = {}
    for name, record in candidates.items():
        bases = [base.qualified_name for base in record.bases]
        dependencies = set(bases)
        methods: list[NativeMethod] = []
        for method in record.methods:
            if method.access != "public" or method.name.startswith(("qt_", "_")):
                continue
            arguments = [p.type_spelling for p in method.parameters]
            dependencies.update(
                re.findall(r"\bQ[A-Za-z0-9_]+\b", " ".join([method.return_type, *arguments]))
            )
            methods.append(
                {
                    "minimum_args": sum(p.default_value is None for p in method.parameters),
                    "defaults": [p.default_value for p in method.parameters],
                    "owner": name,
                    "name": method.name,
                    "result": method.return_type,
                    "args": arguments,
                    "parameter_names": [p.name for p in method.parameters],
                    "const": method.is_const,
                    "static": method.is_static,
                    "variadic": method.is_varargs,
                    "deprecated": method.is_deprecated,
                }
            )
        abstract = bool(abstract_methods(name))
        constructors: list[list[str]] = []
        for ctor in record.constructors:
            if (
                ctor.is_deleted
                or ctor.is_deprecated
                or ctor.is_varargs
                or tuple(re.sub(r"\s+", "", p.type_spelling) for p in ctor.parameters)
                in deleted.get(name, set())
            ):
                continue
            required = sum(p.default_value is None for p in ctor.parameters)
            for count in range(required, len(ctor.parameters) + 1):
                constructors.append([p.type_spelling for p in ctor.parameters[:count]])
        classes[name] = {
            "constructors": constructors,
            "copyable": not record.has_deleted_copy_constructor and name not in noncopyable,
            "fields": [
                {
                    "name": field.name,
                    "type": field.type_spelling,
                    "static": field.is_static,
                    "readonly": field.is_const,
                }
                for field in record.fields
            ],
            "bases": bases,
            "abstract": abstract,
            "default_ctor": not abstract
            and any(
                all(p.default_value is not None for p in ctor.parameters)
                for ctor in record.constructors
            ),
            "source": record.source_file or "",
            "dependencies": sorted(dependencies),
            "methods": methods,
        }
    return classes, flags
