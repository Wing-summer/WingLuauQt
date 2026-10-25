# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Emit browse-only symbol pages from the same generated declaration model."""

from __future__ import annotations

import hashlib
import json
import re

from .declaration_tables import table_fields
from .definition_graph import DefinitionFiles
from .function_naming import rename_declarations
from .models import JsonObject


def emit_symbol_catalog(
    types: dict[str, str], values: dict[str, str], public: set[str],
    globals_: list[str], files: DefinitionFiles, prefix: str, categories: JsonObject,
    module_types: dict[str, list[str]] | None = None,
) -> None:
    """Write a small module directory and lazily readable direct-member pages."""
    pending: dict[str, tuple[str, str, bool, tuple[str, ...]]] = {}
    roots: list[JsonObject] = []

    def shape(source: str, seen: set[str] | None = None) -> str:
        """Resolve a type alias without expanding tables recursively."""
        seen = set() if seen is None else seen
        source = source.strip()
        if source in types and source not in seen:
            seen.add(source)
            return shape(types[source].split("=", 1)[1], seen)
        parts = table_fields(source, "&")
        if len(parts) > 1:
            tables = [shape(part, set(seen)) for part in parts]
            if all(table.startswith("{") and table.endswith("}") for table in tables):
                fields: dict[str, str] = {}
                for table in tables:
                    for field in table_fields(table[1:-1]):
                        label = field.split(":", 1)[0].strip()
                        fields[label] = field
                return "{\n" + ",\n".join(fields.values()) + "\n}"
        return source

    def node(name: str, source: str, identity: str, root: bool,
             ancestors: tuple[str, ...] = ()) -> JsonObject:
        """Render one symbol and queue its member page without walking descendants."""
        source = rename_declarations({}, f"declare {name}: {source}").split(":", 1)[1].strip()
        resolved = shape(source)
        is_table = resolved.startswith("{") and resolved.endswith("}")
        call = next((field.split(":", 1)[1] for field in table_fields(resolved[1:-1])
                     if re.match(r"__call\s*:", field)), "") if is_table else ""
        constructor = bool(call) or ((root or name.startswith("Q")) and not is_table and "->" in resolved)
        instance = name if name in types else "_qt_" + name
        if constructor and instance not in types:
            found = re.search(r"->\s*([A-Za-z_]\w*)", call or source)
            instance = found[1] if found else ""
        member_shape = shape(instance) if constructor and instance in types else ""
        is_table = resolved.startswith("{") and resolved.endswith("}")
        has_children = is_table or (member_shape.startswith("{") and member_shape.endswith("}"))
        kind = ("class" if member_shape or (name.startswith("Q") and instance in types) else "module" if is_table else
                "function" if "->" in resolved else "constant")
        detail = f"{name}: {{ ... }}" if has_children else f"{name}: {source}"
        item: JsonObject = {"id": identity, "label": name, "kind": kind,
                            "detail": detail.splitlines()[0], "declaration": detail if is_table else name + ": " + source}
        fingerprint = resolved + "\n" + member_shape
        if has_children and fingerprint not in ancestors:
            filename = prefix + "_symbols_" + hashlib.sha256(identity.encode()).hexdigest()[:16] + ".json"
            item["members"] = filename
            pending[identity] = (resolved, member_shape, constructor, (*ancestors, fingerprint))
        return item

    for name, body in sorted(values.items()):
        root = node(name, body, "module:" + name, True)
        category = categories.get(name, "data")
        if not isinstance(category, str):
            raise ValueError("Symbol categories must be strings")
        root.update({"category": category, "require": name not in public})
        roots.append(root)
    for source in globals_:
        match = re.match(r"declare function (\w+)\((.*)\): (.*)", source, re.DOTALL)
        if match:
            root = node(match[1], f"({match[2]}) -> {match[3]}", "global:" + match[1], False)
            root.update({"category": categories.get(match[1], "logging"), "require": False})
            roots.append(root)
    while pending:
        identity = next(iter(pending))
        resolved, instance, _, ancestors = pending.pop(identity)
        members: dict[str, str] = {}
        for body in (instance, resolved):
            if body.startswith("{") and body.endswith("}"):
                for field in table_fields(body[1:-1]):
                    match = re.match(r"(\w+)\s*:\s*(.*)", field, re.DOTALL)
                    if match and not match[1].startswith("__"):
                        members[match[1]] = match[2]
        children = [node(name, body, identity + "/" + name, False, ancestors)
                    for name, body in sorted(members.items())]
        if identity.startswith("module:") and module_types:
            for name in sorted(module_types.get(identity.removeprefix("module:"), [])):
                child = node(name, name, identity + "/type:" + name, False, ancestors)
                child["kind"] = "interface"
                child["detail"] = "type " + name
                children.append(child)
        filename = prefix + "_symbols_" + hashlib.sha256(identity.encode()).hexdigest()[:16] + ".json"
        files.sources[filename] = json.dumps({"children": children}, ensure_ascii=False, indent=2) + "\n"
    files.sources[prefix + "_symbols.json"] = json.dumps({"version": 1, "roots": roots}, ensure_ascii=False, indent=2) + "\n"
