# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Partition generated type declarations without duplicating recursive identities."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .declaration_tables import table_fields


@dataclass
class DefinitionFiles:
    """Collect generated definition sources and their ordered ambient preload set."""

    #: Sources relative to the deployed definition directory.
    sources: dict[str, str] = field(default_factory=lambda: dict[str, str]())
    #: Ambient files in dependency order; module-only shards are absent.
    preload: list[str] = field(default_factory=lambda: list[str]())
    #: Component dependencies, including ambient dependencies without require edges.
    dependencies: dict[str, list[str]] = field(default_factory=lambda: dict[str, list[str]]())


def identifiers(source: str) -> set[str]:
    """Read identifiers while excluding generated comments and quoted string literals."""
    clean = re.sub(r'--[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', "", source)
    return set(re.findall(r"\b[A-Za-z_]\w*\b", clean))


def components(graph: dict[str, set[str]]) -> list[list[str]]:
    """Return strongly connected components in dependency-first deterministic order."""
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    result: list[list[str]] = []

    def visit(name: str) -> None:
        """Visit one generated type in Tarjan's depth-first traversal."""
        indices[name] = low[name] = len(indices)
        stack.append(name)
        active.add(name)
        for dep in sorted(graph[name]):
            if dep not in indices:
                visit(dep)
                low[name] = min(low[name], low[dep])
            elif dep in active:
                low[name] = min(low[name], indices[dep])
        if low[name] == indices[name]:
            group: list[str] = []
            while True:
                item = stack.pop()
                active.remove(item)
                group.append(item)
                if item == name:
                    break
            result.append(sorted(group))

    for name in sorted(graph):
        if name not in indices:
            visit(name)
    return result


def declaration(source: str) -> str:
    """Preserve native userdata identity with nominal rather than structural types."""
    match = re.fullmatch(r"type ((?:_qt_|__WingLuauQtCallable_)\w+) = (?:(\w+) & )?\{(.*)\}", source, re.DOTALL)
    if not match:
        return "export " + source
    name, base, members = match.groups()
    parent = " extends " + base if base else ""
    fields: list[str] = []
    for item in table_fields(members):
        label, signature = item.split(":", 1)
        for overload in table_fields(signature, "&"):
            fields.append("    " + label.strip() + ": " + overload.strip())
    return f"declare extern type {name}{parent} with\n" + "\n".join(fields) + "\nend"


def partition(
    types: dict[str, str], public: list[str], entries: dict[str, str],
    files: DefinitionFiles, prefix: str,
) -> dict[str, str]:
    """Emit ambient dependencies once and ordinary module shards for private types."""
    names = set(types)
    graph = {name: (identifiers(source) & names) - {name} for name, source in types.items()}
    needed: set[str] = set()
    todo = list(set[str]().union(*(identifiers(source) & names for source in public)))
    while todo:
        name = todo.pop()
        if name not in needed:
            needed.add(name)
            todo.extend(graph[name])
    owner: dict[str, str] = {}
    for group in components(graph):
        ordered: list[str] = []
        def order(name: str) -> None:
            """Visit a nominal base before a derived type in the same component."""
            if name in ordered:
                return
            base = re.match(r"type \w+ = (\w+) & \{", types[name])
            if base and base[1] in group:
                order(base[1])
            ordered.append(name)
        for name in group:
            order(name)
        ambient = any(name in needed for name in group)
        digest = hashlib.sha256("\n".join(group).encode()).hexdigest()[:12]
        filename = f"{prefix}_types_{digest}.d.luau"
        dependencies = sorted(set[str]().union(*(graph[name] for name in group)) - set(group))
        imports: list[str] = []
        if not ambient:
            modules = sorted({owner[name] for name in dependencies if name not in needed})
            labels = {module: f"types{i}" for i, module in enumerate(modules)}
            imports.extend(f'local {label} = require("./{module}")' for module, label in labels.items())
            imports.extend(f"type {name} = {labels[owner[name]]}.{name}" for name in dependencies if name not in needed)
        source = "\n".join(["--!strict", "-- Generated type component.", *imports,
                              *(declaration(types[name]) for name in ordered)]) + "\n"
        if ambient:
            files.preload.append(filename)
        else:
            source += "return {}\n"
        files.sources[filename] = source
        files.dependencies[filename] = sorted({owner[name] for name in dependencies})
        owner.update(dict.fromkeys(group, filename))
    output: dict[str, str] = {}
    for module, source in entries.items():
        dependencies = sorted((identifiers(source) & names) - needed)
        modules = sorted({owner[name] for name in dependencies})
        labels = {name: f"types{i}" for i, name in enumerate(modules)}
        imports = [f'local {label} = require("./{name}")' for name, label in labels.items()]
        imports.extend(f"type {name} = {labels[owner[name]]}.{name}" for name in dependencies)
        files.dependencies[f"{prefix}_{module}.d.luau"] = sorted({owner[name] for name in identifiers(source) & names})
        output[module] = "\n".join(["--!strict", *imports, source]) + "\n"
    return output
