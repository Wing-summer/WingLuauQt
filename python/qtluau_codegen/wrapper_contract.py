# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Read adapted signatures from the framework's simple C++ wrapper declarations."""

from __future__ import annotations

import re

from .assets import support_root
from .models import Method, Parameters


def _type(spelling: str, parameter: str = "") -> str:
    """Map a supported wrapper spelling, failing on an unknown public signature."""
    kind = re.sub(r"\bconst\b|[&*\s]", "", spelling)
    primitives = {
        "void": "()",
        "bool": "boolean",
        "int": "number",
        "double": "number",
        "std::string": "string",
    }
    if kind in primitives:
        return primitives[kind]
    if kind == "luabridge::LuaRef":
        return "() -> ()" if parameter == "callback" else "any"
    if kind.startswith("QtTypedWidgetRef<"):
        return "_qt_" + kind.removeprefix("QtTypedWidgetRef<").removesuffix(">")
    if kind.startswith("Qt") and kind.endswith("Ref"):
        return "_qt_Q" + kind[2:-3]
    raise ValueError(f"Unsupported wrapper contract type: {spelling}")


def wrapper_methods() -> dict[str, dict[str, Method]]:
    """Return generic bridge method signatures from maintained declarations.

    Only the maintained framework declaration grammar is accepted. Application
    C++ uses the native scanners instead. VM injection parameters are omitted.
    """
    root = support_root()
    header = (root / "include/qtluau/widget_wrappers.hpp").read_text()
    variant_header = root / "include/qtluau/value_conversion.hpp"
    if variant_header.is_file():
        header += "\n" + variant_header.read_text()
    object_header = root / "include/qtluau/qobject_value.hpp"
    if object_header.is_file():
        header += "\n" + object_header.read_text()
    result: dict[str, dict[str, Method]] = {}
    for entry in re.finditer(
        r"^(?:class|struct) (\w+)(?: : public Qt\w+Ref)? \{(.*?)^};",
        header,
        re.M | re.S,
    ):
        wrapper, body = entry.groups()
        methods: dict[str, Method] = {}
        body = re.sub(r"//[^\n]*", "", body.split("protected:")[0].split("private:")[0])
        for declaration in re.finditer(
            r"([\w:< >*&]+?)\s+(\w+)\(([^;{}]*)\)\s*(?:const)?\s*;", body
        ):
            returns, name, arguments = declaration.groups()
            if name == wrapper or name == "get":
                continue
            parameters: Parameters = []
            for argument in arguments.split(","):
                argument = argument.strip()
                if not argument or "lua_State" in argument:
                    continue
                raw = argument.split("=", 1)[0].strip()
                match = re.fullmatch(r"(.+?)(\w+)", raw)
                if match is None:
                    raise ValueError(f"Unsupported wrapper argument: {argument}")
                kind, label = match.groups()
                mapped = _type(kind, label)
                if "=" in argument:
                    mapped += "?"
                parameters.append((label, mapped))
            signature: Method = (
                name,
                parameters,
                _type(returns.strip().removeprefix("public:").strip()),
            )
            previous = methods.get(name)
            if previous is not None and previous[1] != parameters:
                if len(previous[1]) != len(parameters):
                    raise ValueError(f"Unsupported wrapper overload arity: {wrapper}::{name}")
                merged: Parameters = [
                    (old[0], " | ".join(dict.fromkeys([*old[1].split(" | "), new[1]])))
                    for old, new in zip(previous[1], parameters, strict=True)
                ]
                methods[name] = (name, merged, signature[2])
            else:
                methods.setdefault(name, signature)
        result[wrapper] = methods
    return result
