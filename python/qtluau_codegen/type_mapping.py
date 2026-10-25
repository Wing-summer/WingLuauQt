# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Representable C++ signatures and their runtime conversion expressions."""

from __future__ import annotations

import re


def mapped_type(
    spelling: str,
    result: bool = False,
    object_types: set[str] | None = None,
    widget_types: set[str] | None = None,
    layout_types: set[str] | None = None,
) -> tuple[str, str, str] | None:
    # Mutable references, pointers and unsupported signatures need an explicit host facade.
    """Return supported C++ and Luau spellings for a native type, or None."""
    if "&" in spelling and not spelling.startswith("const "):
        return None
    bare = re.sub(r"\bconst\b|[&]", "", spelling).strip()
    pointer = re.fullmatch(r"(Q\w+)\s*\*", bare)
    if pointer is not None and object_types is not None and pointer[1] in object_types:
        if "const" in spelling:
            return None
        native = pointer[1]
        lua = (
            "_qt_QWidget"
            if widget_types is not None and native in widget_types
            else (
                "_qt_QLayout"
                if layout_types is not None and native in layout_types
                else "_qt_QObject"
            )
        )
        if result and ((widget_types is not None and native in widget_types) or
                       (layout_types is not None and native in layout_types)):
            lua = "_qt_" + native
        return (
            "luabridge::LuaRef" if result else f"QtArgument<{bare}>",
            lua,
            "qtToLua(L, {expr})" if result else "{expr}.value",
        )
    if re.search(r"\b(?:const_)?(?:reverse_)?iterator\b", bare):
        return None
    aliases = {
        "QByteArray": "string",
        "QByteArrayList": "{string}",
        "QStringList": "{string}",
        "QVariantList": "{any}",
        "QVariantMap": "{[string]: any}",
        "QVariantHash": "{[string]: any}",
        "QVariant": "any",
    }
    lua_container = aliases.get(bare)
    if not lua_container:
        match = re.fullmatch(r"(QList|QVector)<(.+)>", bare)
        if match:
            element = mapped_type(
                match.group(2).strip(),
                object_types=object_types,
                widget_types=widget_types,
                layout_types=layout_types,
            )
            if element:
                lua_container = "{" + element[1] + "}"
        match = re.fullmatch(r"(QMap|QHash)<QString,\s*(.+)>", bare)
        if match:
            element = mapped_type(
                match.group(2).strip(),
                object_types=object_types,
                widget_types=widget_types,
                layout_types=layout_types,
            )
            if element:
                lua_container = "{[string]: " + element[1] + "}"
    if lua_container:
        return (
            "luabridge::LuaRef" if result else f"QtArgument<{bare}>",
            lua_container,
            "qtToLua(L, {expr})" if result else "{expr}.value",
        )
    if bare == "void" and result:
        return ("void", "()", "{expr}")
    if bare == "std::string":
        return ("std::string", "string", "{expr}")
    if bare == "QAnyStringView":
        return (
            "std::string",
            "string",
            "toUtf8String({expr})" if result else "QAnyStringView({expr})",
        )
    if bare == "QString":
        return (
            "luabridge::LuaRef" if result else "QtArgument<QString>",
            "string",
            "qtToLua(L, {expr})" if result else "{expr}.value",
        )
    if bare in ("QColor", "QFont"):
        return (bare, "_qt_" + bare, "{expr}")
    if bare == "bool":
        return ("bool", "boolean", "{expr}")
    if bare == "qsizetype":
        return (
            "double" if result else "QtArgument<qsizetype>",
            "number",
            '([](qsizetype value) {{ if (value < -9007199254740991LL || value > 9007199254740991LL) throw std::out_of_range("Qt size exceeds Luau number precision"); return static_cast<double>(value); }})({expr})'
            if result
            else "{expr}.value",
        )
    if bare in {
        "qint64",
        "quint64",
        "qlonglong",
        "qulonglong",
        "quintptr",
        "qintptr",
        "long long",
        "unsigned long long",
    }:
        return (
            "luabridge::LuaRef" if result else f"QtArgument<{bare}>",
            "number",
            "qtToLua(L, {expr})" if result else "{expr}.value",
        )
    if re.fullmatch(r"q(?:u?int(?:8|16|32|64)|u?intptr)", bare):
        return (bare, "number", "{expr}")
    if bare in (
        "int",
        "unsigned int",
        "short",
        "unsigned short",
        "long",
        "unsigned long",
        "long long",
        "unsigned long long",
        "float",
        "double",
        "qreal",
    ):
        return (bare, "number", "{expr}")
    return None


def is_table_container(spelling: str) -> bool:
    """Recognize supported table conversions without relying on Qt name suffixes."""
    mapped = mapped_type(spelling)
    return mapped is not None and mapped[1].startswith("{")
