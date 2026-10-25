# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Discover Lua C registration tables and consume adjacent native type contracts."""

from __future__ import annotations

import pathlib
import re

from .extensions import paths
from .models import JsonObject, object_list_field, string_list_field


def emit_lua_c_apis(config: JsonObject, base: pathlib.Path, report: JsonObject | None = None) -> dict[str, str]:
    """Generate definitions from native exports, failing on missing signature semantics.

    The registration tables own names. Source-adjacent ``@luau`` comments describe
    stack semantics that an int(lua_State*) declaration cannot express. Arbitrary
    C declaration parsing remains a runtime responsibility.
    """
    result: dict[str, str] = {}
    for entry in object_list_field(config, "lua_c_apis"):
        module = entry.get("module")
        if not isinstance(module, str) or not module.isidentifier():
            raise ValueError("Lua C API module must be an identifier")
        root = entry.get("root")
        if not isinstance(root, str) or not root.isidentifier():
            raise ValueError("Lua C API root must select a native record")
        sources = paths(base, string_list_field(entry, "sources"))
        source = "\n".join(path.read_text() for path in sources)
        contracts = {
            native: (group, signature)
            for group, signature, native in re.findall(
                r"// @luau (factory|instance|callback) ([^\n]+)\n\s*static int (\w+)\(lua_State \*L\)", source
            )
        }
        exports: dict[str, str] = {}
        for table in re.findall(r"luaL_Reg\s+const\s+\w+\[\]\s*=\s*\{(.*?)\n\s*\};", source, re.DOTALL):
            exports.update({native: name for name, native in re.findall(r'\{"(\w+)",\s*(\w+)\}', table)})
        exports.update({native: name for native, name in re.findall(
            r'lua_pushc(?:function|closure)\(L,\s*(\w+)(?:,\s*\d+)?\);\s*lua_setfield\(L,\s*(?:-2|inst_idx),\s*"(\w+)"\);', source[source.index("struct " + root): ]
        )})
        # Resolve callback names from the actual metatable index dispatcher.
        exports.update({native: name for name, native in re.findall(
            r'!std::strcmp\(\w+,\s*"(\w+)"\).*?lua_pushcfunction\(L,\s*(\w+)\)', source, re.DOTALL
        ) if native in contracts})
        missing = set(exports) - set(contracts)
        unused = set(contracts) - set(exports)
        if missing or unused:
            raise ValueError(f"Lua C API contract mismatch: missing={sorted(missing)}, unused={sorted(unused)}")
        groups: dict[str, list[str]] = {"factory": [], "instance": [], "callback": []}
        for native, name in sorted(exports.items(), key=lambda item: item[1]):
            group, signature = contracts[native]
            groups[group].append(f"    {name}: {signature},")
        fields = dict(re.findall(r"// @luau-field (\w+): ([^\n]+)", source))
        instance_fields = set(re.findall(r'lua_setfield\(L,\s*inst_idx,\s*"(\w+)"\)', source))
        for name in instance_fields - set(fields):
            if name in {exports[native] for native in exports if contracts[native][0] == "instance"}:
                continue
            if re.search(r'lua_pushliteral\(L,\s*\w+\);\s*lua_setfield\(L,\s*inst_idx,\s*"' + name + r'"\)', source):
                fields[name] = "string"
            else:
                raise ValueError("Missing Lua C field semantics: " + name)
        groups["instance"].extend(f"    {name}: {kind}," for name, kind in sorted(fields.items()))
        types = [f"type {declaration}" for declaration in re.findall(r"// @luau-type ([^\n]+)", source)]
        types.extend("type " + name + " = {\n" + "\n".join(groups[group]) + "\n}"
                     for group, name in [("callback", "Callback"), ("instance", "Instance"), ("factory", "Factory")])
        result[module] = "\n\n".join(types) + f"\n\ndeclare {module}: Factory\n"
        if report is not None:
            report[module] = {"sources": [str(path.relative_to(base)) for path in sources],
                              "exports": {group: sorted(name for native, name in exports.items() if contracts[native][0] == group) for group in groups},
                              "fields": sorted(fields), "missing": [], "unused": []}
    return result
