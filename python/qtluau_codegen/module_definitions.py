# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Emit shared definitions once and small, ordinary Luau module type entries."""

import pathlib
import re

from .declaration_tables import callable_tables, merge_namespace_declarations
from .definition_graph import DefinitionFiles, partition
from .extensions import definitions
from .models import JsonObject
from .symbol_catalog import emit_symbol_catalog

DECLARATION = re.compile(r"^(?:declare |(?:export )?type )", re.MULTILINE)
VALUE = re.compile(r"declare (\w+): (.*)", re.DOTALL)


def split_declarations(source: str) -> tuple[list[str], list[str]]:
    """Split top-level Luau definitions, preserving recursive type aliases.

    Args:
        source: Declaration source with top-level declarations at column zero.

    Returns:
        Structural type aliases and value declarations in source order.

    Raises:
        ValueError: An external type has no closing ``end``.
    """
    types: list[str] = []
    globals_: list[str] = []
    starts = [match.start() for match in DECLARATION.finditer(source)]
    if not starts:
        return types, globals_
    for start, end in zip(starts, [*starts[1:], len(source)], strict=True):
        block = source[start:end].strip()
        # Trailing standalone comments belong to neither declaration.
        block = re.sub(r"\n\s*--[^\n]*(?:\n\s*--[^\n]*)*\s*$", "", block)
        lines = block.splitlines()
        match = re.fullmatch(r"declare extern type (\w+)(?: extends (\w+))? with", lines[0])
        if match:
            name, base = match.groups()
            if "end" not in lines:
                raise ValueError(f"Unterminated external type: {name}")
            members: list[str] = []
            for member in lines[1:lines.index("end")]:
                function = re.fullmatch(r"\s*function (\w+)\(self(?:, (.*))?\): (.*)", member)
                if function:
                    method, args, result = function.groups()
                    member = f"    {method}: (self: {name}{', ' + args if args else ''}) -> {result}"
                if member.strip():
                    members.append(member.rstrip(",") + ",")
            types.append(f"type {name} = {base + ' & ' if base else ''}{{\n" + "\n".join(members) + "\n}")
        elif block.startswith(("type ", "export type ")):
            types.append(block.removeprefix("export "))
        else:
            globals_.append(block)
    return types, globals_


def module_definitions(
    directory: pathlib.Path, extensions: list[JsonObject], extra: dict[str, str] | None = None,
    public_modules: set[str] | None = None,
    files: DefinitionFiles | None = None, prefix: str = "bindings",
    categories: JsonObject | None = None,
) -> dict[str, str]:
    """Build one shared definition file and one type entry per named module.

    Args:
        directory: Intermediate common and Qt declaration directory.
        extensions: Resolved extension metadata.
        extra: Application declaration sources keyed by module name.
        public_modules: Named tables also exposed as public globals.

    Returns:
        Sources keyed by module name; the empty key contains shared definitions.

    Raises:
        ValueError: Conflicting type names or public/module names are found.
    """
    common_types, common_globals = split_declarations((directory / "common.d.luau").read_text())
    qt_types, qt_globals = split_declarations((directory / "qt.d.luau").read_text())
    extension_types, _ = split_declarations(definitions(extensions))
    types = [*common_types, *qt_types, *extension_types]
    modules = {"": common_globals, "qt": qt_globals}
    module_types: dict[str, list[str]] = {}
    for module, source in (extra or {}).items():
        aliases, values = split_declarations(source)
        types.extend(aliases)
        module_types[module] = [match[1] for alias in aliases if (match := re.match(r"type ((?!_qt_)\w+)", alias))]
        modules.setdefault(module, []).extend(values)
    for module in sorted({str(e.get("module", e["namespace"])) for e in extensions}):
        _, values = split_declarations(definitions([e for e in extensions if e.get("module", e["namespace"]) == module]))
        modules.setdefault(module, []).extend(values)
    public = public_modules or set()
    for module, values in modules.items():
        if module:
            modules[module] = [merge_namespace_declarations("\n\n".join(values))]
    for module in sorted(public):
        if module in modules:
            modules[""].extend(modules[module])
    public_names: set[str] = set()
    value_types: dict[str, str] = {}
    for module, values in modules.items():
        for value in values:
            match = VALUE.fullmatch(value)
            if match:
                name, body = match.groups()
                if module == "":
                    if name in public_names or (name in modules and name not in public):
                        raise ValueError(f"Public binding masks another declaration/module: {name}")
                    public_names.add(name)
                previous = value_types.setdefault(name, body)
                if previous != body:
                    raise ValueError(f"Conflicting value declaration: {name}")
    aliases = {name: "__WingLuauQtValue_" + name for name in value_types}

    def references(source: str) -> str:
        """Replace value-type references with shared aliases without inlining."""
        return re.sub(r"typeof\((\w+)\)", lambda match: aliases.get(match[1], match[0]), source)

    unique_types: dict[str, str] = {}
    for source in types:
        match = re.match(r"type (\w+)", source)
        if not match:
            raise ValueError("Invalid type declaration")
        previous = unique_types.setdefault(match[1], source)
        if previous != source:
            raise ValueError(f"Conflicting type declaration: {match[1]}")
    all_types = {name: references(source) for name, source in unique_types.items()}
    all_types.update({aliases[name]: f"type {aliases[name]} = {references(body)}"
                      for name, body in value_types.items()})
    globals_: list[str] = []
    for value in modules[""]:
        match = VALUE.fullmatch(value)
        globals_.append(f"declare {match[1]}: {aliases[match[1]]}" if match else references(value))
    entries = {module: f"return (nil :: any) :: {aliases[module]}"
               for module in modules if module}
    bundle = files if files is not None else DefinitionFiles()
    emit_symbol_catalog(all_types, value_types, public_names, globals_, bundle, prefix, categories or {}, module_types)
    declaration_types: dict[str, str] = {}
    for name, source in all_types.items():
        declaration_types[name] = source if name.startswith("_qt_") else callable_tables(source, declaration_types)
    result = partition(declaration_types, globals_, entries, bundle, prefix)
    remaining_globals = list(globals_)
    if files is not None:
        for module in sorted(public):
            declaration = f"declare {module}: {aliases[module]}"
            if declaration in remaining_globals:
                remaining_globals.remove(declaration)
                result[module] = declaration + "\n"
                bundle.preload.append(f"{prefix}_{module}.d.luau")
    result[""] = "\n\n".join(remaining_globals) + "\n"
    if files is None:
        # Legacy in-memory callers have no file resolver; retain a complete ambient unit.
        result[""] = "\n\n".join("export " + source for source in all_types.values()) + "\n" + result[""]
        result.update({module: "--!strict\n" + source + "\n" for module, source in entries.items()})
    return result
