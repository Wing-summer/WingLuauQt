# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate callback registration contracts and definitions from one descriptor."""

from __future__ import annotations

import pathlib
import re

from .extensions import identifier, write
from .generate_definitions import emit_ir_function
from .models import JsonObject, object_list_field
from .module_policy import requires_module


def emit_callbacks(config: JsonObject, output: pathlib.Path) -> dict[str, str]:
    """Emit validated host callback contracts and matching module definitions."""
    header = ["#pragma once", '#include "qtluau/bindings.hpp"', "namespace qtluau {"]
    source = [
        '#include "qtluau/packages.hpp"',
        '#include "callback_bindings.hpp"',
        "#include <stdexcept>",
        "namespace qtluau {",
    ]
    initializers = [
        "// Generated native callback initializers; include inside the host registration scope."
    ]
    definitions: dict[str, str] = {}
    for entry in object_list_field(config, "callback_sets"):
        name = identifier(entry["name"])
        module = str(entry.get("module", ""))
        namespace = str(entry.get("namespace", module))
        if namespace:
            identifier(namespace)
        if module:
            identifier(module)
            if namespace != module:
                raise ValueError("Named callback modules must use their module namespace")
        functions = object_list_field(entry, "functions")
        native: list[str] = []
        for function in functions:
            symbol = function.get("native", "")
            if not isinstance(symbol, str):
                raise ValueError("Callback native symbols must be strings")
            native.append(symbol)
        if any(native):
            if not all(
                re.fullmatch(r"&?[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*", value) for value in native
            ):
                raise ValueError("Every callback in an initialized set needs a valid native symbol")
            initializers.append(f"qtluau::register{name}(L, {{" + ", ".join(native) + "});")

        names = [identifier(f["name"]) for f in functions]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate callback function name")
        header.append(f"struct {name} {{")
        header.extend(f"    lua_CFunction {fn} = nullptr;" for fn in names)
        header.extend(["};", f"void register{name}(lua_State *L, const {name} &callbacks);"])
        source.append(f"void register{name}(lua_State *L, const {name} &callbacks) {{")
        source.extend(
            f'if (!callbacks.{fn}) {{ throw std::invalid_argument("Missing callback: {fn}"); }}'
            for fn in names
        )
        source.append(
            "auto scope = luabridge::getGlobalNamespace(L)"
            + (f'.beginNamespace("{namespace}")' if namespace else "")
            + ";"
        )
        source.extend(f'scope.addFunction("{fn}", callbacks.{fn});' for fn in names)
        if module:
            source.extend(
                [
                    f'lua_getglobal(L, "{module}");',
                    f'rememberModule(L, "{module}", -1);',
                    "lua_pop(L, 1);",
                ]
            )
        if module and requires_module(config, module):
            source.extend(["lua_pushnil(L);", f'lua_setglobal(L, "{module}");'])
        source.append("}")
        text = "\n".join(emit_ir_function(f) for f in functions) + "\n"
        if namespace:
            fields: list[str] = []
            for line in text.splitlines():
                match = re.fullmatch(r"declare function (\w+)\((.*)\): (.*)", line)
                if not match:
                    raise ValueError("Cannot render callback definition")
                fields.append(f"    {match[1]}: ({match[2]}) -> {match[3]},")
            text = f"declare {namespace}: {{\n" + "\n".join(fields) + "\n}\n"
        definitions[module] = definitions.get(module, "") + text
    header.append("}")
    source.append("}")
    write(output / "callback_initializers.inc", "\n".join(initializers) + "\n")
    write(output / "callback_bindings.hpp", "\n".join(header) + "\n")
    write(output / "callback_bindings.cpp", "\n".join(source) + "\n")
    return definitions
