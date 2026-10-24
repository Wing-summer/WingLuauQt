# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Extract declared C++ members, retaining access information absent from tsujikiri IR.

The libclang dependency comes from tsujikiri. This boundary describes only the
small cursor API needed here, keeping untyped vendor objects out of generators.
"""

from __future__ import annotations

import importlib
import pathlib
import shutil
from collections.abc import Iterable
from typing import Protocol, TypedDict, cast

from .discovery import command
from .models import NativeMethod


class Enum(Protocol):
    """Describe the named libclang enum values used at the typed boundary."""
    #: Declaration or source file name.
    name: str


class File(Protocol):
    """Expose the native source file name without a vendor-specific object."""
    #: Declaration or source file name.
    name: str


class Location(Protocol):
    """Describe a source file and byte offset for member extraction."""
    #: Source file associated with a cursor.
    file: File | None
    #: Byte offset within the source file.
    offset: int


class Type(Protocol):
    """Describe native type spellings and relevant qualifiers."""
    #: Compiler-reported declaration or type spelling.
    spelling: str

    def is_const_qualified(self) -> bool:
        """Report whether the native type is const-qualified."""
        ...
    def is_function_variadic(self) -> bool:
        """Report whether the native function type accepts variadic arguments."""
        ...


class Cursor(Protocol):
    """Expose the subset of libclang cursor operations needed by the scanner."""
    #: Typed compiler or conversion category.
    kind: Enum
    #: Compiler-reported declaration or type spelling.
    spelling: str
    #: Source location of the declaration.
    location: Location
    #: Native member visibility.
    access_specifier: Enum
    #: Native function result type.
    result_type: Type
    #: Native declaration type.
    type: Type

    def get_children(self) -> Iterable[Cursor]:
        """Iterate direct child declarations of this native cursor."""
        ...
    def get_arguments(self) -> Iterable[Cursor]:
        """Iterate native function parameter declarations."""
        ...
    def is_definition(self) -> bool:
        """Report whether this cursor provides the declaration definition."""
        ...
    def is_static_method(self) -> bool:
        """Report whether the native method is static."""
        ...
    def is_const_method(self) -> bool:
        """Report whether the native method is const-qualified."""
        ...
    def is_deleted_method(self) -> bool:
        """Report whether the native method is explicitly deleted."""
        ...


class Diagnostic(Protocol):
    """Describe a typed compiler diagnostic severity and message."""
    #: Compiler diagnostic severity level.
    severity: int
    #: Compiler-reported declaration or type spelling.
    spelling: str


class TranslationUnit(Protocol):
    """Expose parsed native declarations and their diagnostics."""
    #: Translation-unit root cursor.
    cursor: Cursor
    #: Compiler diagnostics produced by the parse.
    diagnostics: Iterable[Diagnostic]


class Index(Protocol):
    """Describe the libclang translation-unit parsing interface."""
    def parse(self, path: str, args: list[str], options: int = 0) -> TranslationUnit:
        """Parse a source path using the supplied compiler arguments and options."""
        ...


class IndexFactory(Protocol):
    """Construct a typed compiler index."""
    def create(self) -> Index:
        """Create a compiler index for a fresh translation-unit parse."""
        ...


class Clang(Protocol):
    """Expose the typed libclang factory interface."""
    #: Typed index factory supplied by libclang.
    Index: IndexFactory


class Field(TypedDict):
    """Describe a declared native data field and its access."""
    #: Declaration or source file name.
    name: str
    #: Native declaration type.
    type: str
    #: Visibility associated with each native signature.
    access: str
    #: Whether the native field rejects writes.
    readonly: bool


class Members(TypedDict):
    """Group native methods, fields and access metadata for one class."""
    #: Selected method signatures or method names.
    methods: list[NativeMethod]
    #: Declared data fields and their access metadata.
    fields: list[Field]
    #: Visibility associated with each native signature.
    access: dict[str, str]


def scan_members(header: pathlib.Path, flags: list[str]) -> dict[str, Members]:
    """Parse headers with libclang and retain declared member access metadata."""
    clang = cast(Clang, importlib.import_module("clang.cindex"))
    args = ["-x", "c++", "-std=c++17", *flags]
    if shutil.which("clang++"):
        args.append("-resource-dir=" + command(["clang++", "-print-resource-dir"]))
    package_file = importlib.import_module("clang").__file__
    if package_file:
        native = pathlib.Path(package_file).parent / "native"
        if (native / "libcxx").is_dir() and (native / "resource/include").is_dir():
            args.extend(
                [
                    "-nostdinc++",
                    "-isystem" + str(native / "libcxx"),
                    "-isystem" + str(native / "resource/include"),
                ]
            )
    unit = clang.Index.create().parse(str(header), args=args, options=0x200 | 0x40)
    errors = [d.spelling for d in unit.diagnostics if d.severity >= 3]
    if errors:
        raise ValueError(f"Cannot scan {header}:\n" + "\n".join(errors))
    source = header.read_bytes()
    result: dict[str, Members] = {}

    def local(cursor: Cursor) -> bool:
        """Check whether a cursor belongs to an explicitly selected source file."""
        file = cursor.location.file
        return file is not None and pathlib.Path(file.name).resolve() == header.resolve()

    def visit(cursor: Cursor, namespace: list[str]) -> None:
        """Visit native declarations while retaining access and ownership metadata."""
        for node in cursor.get_children():
            if not local(node):
                continue
            if node.kind.name == "NAMESPACE":
                visit(node, [*namespace, node.spelling])
            elif node.kind.name in {"CLASS_DECL", "STRUCT_DECL"} and node.is_definition():
                name = "::".join([*namespace, node.spelling])
                record: Members = {"methods": [], "fields": [], "access": {}}
                for member in node.get_children():
                    # Q_OBJECT emits helper declarations at its expansion location.
                    # They belong to Qt's implementation, not the user's declared API.
                    token = source[member.location.offset : member.location.offset + 24]
                    if token.startswith((b"Q_OBJECT", b"Q_GADGET")):
                        continue
                    access = member.access_specifier.name.lower()
                    if (
                        member.kind.name == "CXX_METHOD"
                        and not member.is_static_method()
                        and not member.is_deleted_method()
                    ):
                        method: NativeMethod = {
                            "owner": name,
                            "name": member.spelling,
                            "result": member.result_type.spelling,
                            "args": [a.type.spelling for a in member.get_arguments()],
                            "const": member.is_const_method(),
                            "static": False,
                            "variadic": member.type.is_function_variadic(),
                            "deprecated": False,
                        }
                        record["methods"].append(method)
                        signature = (
                            member.spelling
                            + "("
                            + ",".join(method["args"])
                            + ")"
                            + (" const" if method["const"] else "")
                        )
                        record["access"][signature] = access
                    elif member.kind.name == "FIELD_DECL":
                        record["fields"].append(
                            {
                                "name": member.spelling,
                                "type": member.type.spelling,
                                "access": access,
                                "readonly": member.type.is_const_qualified(),
                            }
                        )
                result[name] = record
                visit(node, [*namespace, node.spelling])

    visit(unit.cursor, [])
    return result
