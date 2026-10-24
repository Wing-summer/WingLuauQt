# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Derive value-wrapper methods and registration lambdas from native SDK records."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Method, NativeClass, NativeMethod
from .type_mapping import mapped_type


@dataclass(frozen=True)
class ValueMethod:
    """Describe one representable native value method overload."""

    #: Native SDK method record.
    native: NativeMethod
    #: Converted parameter spellings, Luau types and expressions.
    arguments: list[tuple[str, str, str]]
    #: Converted result spellings, Luau type and expression.
    result: tuple[str, str, str]

    def definition(self, owner: str) -> Method:
        """Return a Luau method signature with same-value input support."""
        return (
            self.native["name"],
            [
                (f"arg{i}", "string | $self" if owner in self.native["args"][i] else arg[1])
                for i, arg in enumerate(self.arguments)
            ],
            self.result[1],
        )

    def lambda_code(self, wrapper: str) -> str:
        """Render an inline native call with conversion and character bounds checks."""
        params = ", ".join(f"{arg[0]} arg{i}" for i, arg in enumerate(self.arguments))
        values = [arg[2].format(expr=f"arg{i}") for i, arg in enumerate(self.arguments)]
        call = f"self.native().{self.native['name']}({', '.join(values)})"
        expression = self.result[2].format(expr=call)
        checks = ""
        character = re.sub(r"[&\s]|const", "", self.native["result"]) in {"QChar", "char"}
        if character and not values:
            checks = (
                'if (self.native().isEmpty()) throw std::out_of_range("Empty character sequence"); '
            )
        elif character and len(values) == 1 and self.arguments[0][1] == "number":
            checks = f'if ({values[0]} < 0 || {values[0]} >= self.native().size()) throw std::out_of_range("Character index out of range"); '
        result = ("" if self.result[0] == "void" else "return ") + expression + ";"
        state = ", lua_State *L" if "qtToLua" in expression else ""
        return f"[]({wrapper} &self{', ' if params else ''}{params}{state}) {{ {checks}{result} }}"


def value_methods(name: str, record: NativeClass) -> list[ValueMethod]:
    """Select callable SDK overloads supported by the generic conversion boundary."""
    result: list[ValueMethod] = []
    signatures: set[tuple[str, tuple[str, ...]]] = set()
    for method in record["methods"]:
        if (
            method["static"]
            or method["deprecated"]
            or method["variadic"]
            or method["name"].startswith("operator")
        ):
            continue
        native_result = re.sub(r"\bconst\b|\s", "", method["result"])
        returned = mapped_type(method["result"], True)
        if native_result in {name + "&", name + "&&"}:
            returned = ("void", "()", "{expr}")
        elif native_result == "QChar":
            returned = ("std::string", "string", "toUtf8String(QString({expr}))")
        elif native_result == "char":
            returned = ("int", "number", "static_cast<unsigned char>({expr})")
        if returned is None:
            continue
        for count in range(
            method.get("minimum_args", len(method["args"])), len(method["args"]) + 1
        ):
            arguments = [mapped_type(arg) for arg in method["args"][:count]]
            if any(arg is None for arg in arguments):
                continue
            checked = [arg for arg in arguments if arg is not None]
            signature = (method["name"], tuple(arg[0] for arg in checked))
            if signature in signatures:
                continue
            signatures.add(signature)
            result.append(ValueMethod(method, checked, returned))
    return result
