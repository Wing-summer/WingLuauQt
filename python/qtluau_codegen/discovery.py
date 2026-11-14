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
import sys
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from typing import TYPE_CHECKING, NamedTuple, cast

from .models import NativeClass, NativeMethod

if TYPE_CHECKING:
    from tsujikiri.configurations import SourceConfig
    from tsujikiri.parse_cache import ParseResult

#: Qt's compiler annotation hooks, shared by IR and supplemental scans.
QT_ANNOTATIONS = (
    'QT_ANNOTATE_ACCESS_SPECIFIER(x)=__attribute__((annotate(#x)))',
    'QT_ANNOTATE_FUNCTION(x)=__attribute__((annotate(#x)))',
)

# Enum declarations discovered alongside native classes, keyed by qualified type.
SDK_ENUMS: dict[str, dict[str, int]] = {}
#: Fully resolved QFlags aliases, discovered from compiler typedef declarations.
SDK_FLAGS: dict[str, str] = {}
#: Container aliases resolved from compiler declarations, including global aliases.
SDK_CONTAINER_ALIASES: dict[str, str] = {}
#: Native free functions discovered alongside SDK classes.
SDK_FUNCTIONS: list[NativeMethod] = []


class SdkSnapshot(NamedTuple):
    """Cache one component set without leaking metadata into later exports."""
    #: Native class declarations.
    classes: dict[str, NativeClass]
    #: Compiler include flags.
    flags: list[str]
    #: Native enum values.
    enums: dict[str, dict[str, int]]
    #: Flag aliases.
    flag_types: dict[str, str]
    #: Container aliases.
    containers: dict[str, str]
    #: Free functions.
    functions: list[NativeMethod]


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
    snapshot = _scan(tuple(modules))
    SDK_ENUMS.clear()
    SDK_ENUMS.update({name: dict(values) for name, values in snapshot.enums.items()})
    SDK_FLAGS.clear()
    SDK_FLAGS.update(snapshot.flag_types)
    SDK_CONTAINER_ALIASES.clear()
    SDK_CONTAINER_ALIASES.update(snapshot.containers)
    SDK_FUNCTIONS[:] = snapshot.functions
    return snapshot.classes, snapshot.flags


@functools.cache
def is_sdk_source(source: str, modules: tuple[str, ...]) -> bool:
    """Match SDK module directories and macOS frameworks without header lists."""
    source = source.replace("\\", "/")
    return any(f"/{module}/" in source or f"/{module}.framework/" in source for module in modules)


def included_sdk_modules(modules: tuple[str, ...], flags: list[str]) -> tuple[str, ...]:
    """Find sibling SDK modules for namespace ownership of transitive includes.

    A QtWidgets-only scan still needs namespace declarations from QtCore. SDK
    include paths identify module roots; no module dependency list is copied.
    """
    roots: set[pathlib.Path] = set()
    for flag in flags:
        if not flag.startswith("-I") or len(flag) == 2:
            continue
        path = pathlib.Path(flag[2:])
        for directory in (path, *path.parents):
            if directory.name in modules or directory.name.removesuffix(".framework") in modules:
                roots.add(directory.parent)
                break
    result = set(modules)
    for root in roots:
        for directory in root.iterdir():
            name = directory.name.removesuffix(".framework")
            if directory.is_dir() and re.fullmatch(r"Qt[A-Za-z0-9]+", name):
                result.add(name)
    return tuple(sorted(result))


class SemanticMetadata(NamedTuple):
    """Carry isolated compiler metadata back to the generation thread."""

    #: Container aliases with canonical spellings.
    containers: dict[str, str]
    #: QFlags aliases with canonical spellings.
    flag_types: dict[str, str]
    #: Deleted constructor signatures by owner.
    deleted: dict[str, set[tuple[str, ...]]]
    #: Owners with deleted copy constructors.
    noncopyable: set[str]
    #: Named SDK scopes selected before expensive IR extraction.
    namespaces: tuple[str, ...]


def scan_semantics(
    source: pathlib.Path, flags: list[str], modules: tuple[str, ...] = ()
) -> SemanticMetadata:
    """Parse declaration-only Qt metadata without mutating shared SDK state.

    Return alias, constructor and namespace facts. Raise ValueError for compiler
    errors, so partial SDK metadata cannot be published after a failed parse.
    """
    from .member_scan import Clang, Cursor, compiler_arguments

    containers: dict[str, str] = {}
    flag_types: dict[str, str] = {}
    # Semantic deletion survives Qt macros whose token spelling is not '= delete'.
    clang = cast(Clang, importlib.import_module("clang.cindex"))
    unit = clang.Index.create().parse(
        str(source),
        args=[
            *compiler_arguments(flags),
            *[f"-D{annotation}" for annotation in QT_ANNOTATIONS],
        ],
        # Keep going after errors to collect diagnostics, and skip function bodies.
        options=0x200 | 0x40,
    )
    errors = [d.spelling for d in unit.diagnostics if d.severity >= 3]
    if errors:
        raise ValueError("Could not scan Qt SDK metadata:\n" + "\n".join(errors))
    declarations = list(unit.cursor.get_children())
    for cursor in declarations:
        if cursor.kind.name in {"TYPEDEF_DECL", "TYPE_ALIAS_DECL"}:
            canonical = cursor.underlying_typedef_type.get_canonical().spelling
            if re.match(r"Q(?:List|Vector|Map|Hash)<", canonical):
                containers[cursor.spelling] = canonical
    scope_modules = included_sdk_modules(modules, flags)
    owned_namespaces: list[Cursor] = []
    for cursor in declarations:
        if cursor.kind.name != "NAMESPACE" or not cursor.spelling:
            continue
        # A Qt header can reopen a standard-library namespace. Its canonical
        # declaration identifies the owner without a namespace blacklist.
        file = cursor.canonical.location.file
        if file is not None and (
            is_sdk_source(file.name, scope_modules) if modules
            else pathlib.Path(file.name).resolve() == source.resolve()
        ):
            owned_namespaces.append(cursor)
    # tsujikiri 0.33 has no public scope-inventory entry point. Reuse its scope
    # traversal here so nested and inline namespaces match its IR parser exactly.
    iter_scopes = cast(
        Callable[[Iterable[Cursor], list[str], str], Iterable[tuple[Cursor, object, str]]],
        getattr(importlib.import_module("tsujikiri.parser"), "_iter_scope_decls"),
    )
    namespaces = tuple(sorted({scope for _, _, scope in iter_scopes(owned_namespaces, [], "")} - {""}))
    deleted: dict[str, set[tuple[str, ...]]] = {}
    noncopyable: set[str] = set()
    constructor_cursors = (
        child
        for record in declarations
        if (
            record.kind.name in {"CLASS_DECL", "STRUCT_DECL"}
            and re.fullmatch(r"Q[A-Za-z0-9_]+", record.spelling)
        )
        or (record.kind.name == "NAMESPACE" and record.spelling in namespaces)
        for child in record.get_children()
    )
    for cursor in constructor_cursors:
        if cursor.kind.name in {"TYPEDEF_DECL", "TYPE_ALIAS_DECL"}:
            canonical = cursor.underlying_typedef_type.get_canonical().spelling
            parent = cursor.semantic_parent
            if canonical.startswith("QFlags<") and parent is not None:
                flag_types[parent.spelling + "::" + cursor.spelling] = canonical
            elif re.match(r"Q(?:List|Vector|Map|Hash)<", canonical) and parent is not None:
                containers[parent.spelling + "::" + cursor.spelling] = canonical
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
    return SemanticMetadata(containers, flag_types, deleted, noncopyable, namespaces)


def scan_named_sdk(
    source: SourceConfig, flags: list[str], modules: tuple[str, ...]
) -> tuple[SemanticMetadata, ParseResult | None]:
    """Discover SDK-owned scopes and extract their IR in one isolated worker."""
    from tsujikiri.parse_cache import ParseKey, parse_worker

    metadata = scan_semantics(pathlib.Path(source.path), flags, modules)
    result = (
        parse_worker(ParseKey.from_source(source, metadata.namespaces, "qt"), False)
        if metadata.namespaces else None
    )
    return metadata, result


@functools.cache
def _scan(modules: tuple[str, ...]) -> SdkSnapshot:
    """Use tsujikiri IR and retain public constructor default-argument arities."""
    import tempfile

    from tsujikiri.configurations import SourceConfig
    from tsujikiri.ir import IRClass, IRMethod, merge_modules
    from tsujikiri.parse_cache import ParseKey, parse_worker

    SDK_ENUMS.clear()
    SDK_FLAGS.clear()
    SDK_CONTAINER_ALIASES.clear()
    SDK_FUNCTIONS.clear()
    flags = discover_sdk(list(modules))
    if shutil.which("clang++"):
        flags.append("-resource-dir=" + command(["clang++", "-print-resource-dir"]))
    with tempfile.TemporaryDirectory(prefix="qtluau-sdk-") as temporary:
        source = pathlib.Path(temporary) / "qt_scan.hpp"
        source.write_text("\n".join(f"#include <{m}/{m}>" for m in modules))
        errors: list[str] = []
        source_config = SourceConfig(
            path=str(source), parse_args=["-std=c++17", *flags],
            defines=list(QT_ANNOTATIONS),
        )
        # Use tsujikiri's spawn-safe worker and IR merge facilities. The caller
        # extracts globals while one worker inventories and extracts SDK scopes.
        with ProcessPoolExecutor(max_workers=1, mp_context=get_context("spawn")) as executor:
            named_sdk = executor.submit(scan_named_sdk, source_config, flags, modules)
            results = [parse_worker(ParseKey.from_source(source_config, [""], "qt"), False)]
            semantics, named_ir = named_sdk.result()
            if named_ir is not None:
                results.append(named_ir)
        for result in results:
            errors.extend(result.clang_errors)
            if result.stderr_text:
                print(result.stderr_text, file=sys.stderr, end="")
        if errors:
            raise ValueError("tsujikiri could not parse the Qt SDK:\n" + "\n".join(errors))
        module = merge_modules([result.module for result in results])
        SDK_CONTAINER_ALIASES.update(semantics.containers)
        SDK_FLAGS.update(semantics.flag_types)

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
        and is_sdk_source(c.source_file, modules)
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

    for function in module.functions:
        SDK_FUNCTIONS.append({
            "minimum_args": sum(p.default_value is None for p in function.parameters),
            "defaults": [p.default_value for p in function.parameters],
            "owner": "", "name": function.qualified_name,
            "result": function.return_type,
            "args": [p.type_spelling for p in function.parameters],
            "parameter_names": [p.name for p in function.parameters],
            "const": False, "static": True,
            "variadic": function.is_varargs, "deprecated": function.is_deprecated,
        })
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
                    "signal": "qt_signal" in method.attributes,
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
                in semantics.deleted.get(name, set())
            ):
                continue
            required = sum(p.default_value is None for p in ctor.parameters)
            for count in range(required, len(ctor.parameters) + 1):
                constructors.append([p.type_spelling for p in ctor.parameters[:count]])
        classes[name] = {
            "constructors": constructors,
            "using_methods": [using.member_name for using in record.using_declarations
                              if using.access == "public"],
            "copyable": not record.has_deleted_copy_constructor and name not in semantics.noncopyable,
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
    return SdkSnapshot(classes, flags, {name: dict(values) for name, values in SDK_ENUMS.items()},
                       dict(SDK_FLAGS), dict(SDK_CONTAINER_ALIASES), list(SDK_FUNCTIONS))
