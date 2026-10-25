# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Merge contributions to a module without replacing its existing API table."""

import hashlib
import re

TABLE = re.compile(r"^declare (\w+): \{\n(.*?)^\}", re.MULTILINE | re.DOTALL)


def table_fields(body: str, separator: str = ",") -> list[str]:
    """Split top-level fields without adding commas inside nested table types."""
    fields: list[str] = []
    depths = {"{": 0, "(": 0, "[": 0, "<": 0}
    closing = {"}": "{", ")": "(", "]": "[", ">": "<"}
    quote = ""
    escaped = False
    start = 0
    for index, char in enumerate(body):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
        elif char in depths:
            depths[char] += 1
        elif char in closing and not (char == ">" and index and body[index - 1] == "-"):
            depths[closing[char]] -= 1
        elif char == separator and not any(depths.values()):
            if field := body[start:index].strip():
                fields.append(field)
            start = index + 1
    if field := body[start:].strip():
        fields.append(field)
    return fields


def merge_namespace_declarations(source: str) -> str:
    """Merge module table contributions, rejecting duplicate field names."""
    contributions: dict[str, list[str]] = {}
    for match in TABLE.finditer(source):
        contributions.setdefault(match[1], []).append(match[2])
    emitted: set[str] = set()

    def merge(match: re.Match[str]) -> str:
        """Combine table fields for one matched namespace declaration."""
        name = match[1]
        if name in emitted:
            return ""
        emitted.add(name)
        fields: list[str] = []
        names: set[str] = set()
        for body in contributions[name]:
            for line in table_fields(body):
                key = re.match(r"\s*(\w+):", line)
                if key and key[1] in names:
                    raise ValueError(f"Duplicate binding declaration: {name}.{key[1]}")
                if key:
                    names.add(key[1])
                fields.append("    " + line.rstrip(",") + ",")
        return f"declare {name}: {{\n" + "\n".join(fields) + "\n}"

    return TABLE.sub(merge, source)


def callable_tables(source: str, types: dict[str, str]) -> str:
    """Represent native callable namespace tables with their actual metatable type."""
    result: list[str] = []
    cursor = 0
    while cursor < len(source):
        start = source.find("{", cursor)
        if start < 0:
            result.append(source[cursor:])
            break
        result.append(source[cursor:start])
        depth = 1
        end = start + 1
        while end < len(source) and depth:
            if source[end] == "{":
                depth += 1
            elif source[end] == "}":
                depth -= 1
            end += 1
        if depth:
            raise ValueError("Unterminated generated table type")
        body = callable_tables(source[start + 1:end - 1], types)
        fields = table_fields(body)
        call = [field for field in fields if re.match(r"__call\s*:", field)]
        if call or any(":" in field and len(table_fields(field.split(":", 1)[1], "&")) > 1 for field in fields):
            identity = "__WingLuauQtCallable_" + hashlib.sha256(body.encode()).hexdigest()[:12]
            types[identity] = f"type {identity} = {{" + body + "}"
            result.append(identity)
        else:
            result.append("{" + body + "}")
        cursor = end
    return "".join(result)
