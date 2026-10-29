# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Normalize public configuration into canonical, typed common-type policies."""

from __future__ import annotations

import re
from typing import cast

from .catalog import TYPE_DEFAULTS
from .models import CommonTypePolicy, JsonObject, object_field
from .module_policy import KEYWORDS, qt_namespace
from .type_mapping import is_table_container


def common_types(config: JsonObject) -> dict[str, CommonTypePolicy]:
    """Validate canonical type policies and return normalized alias and method settings."""
    common: JsonObject = object_field(config, "common")
    raw: dict[str, JsonObject] = {
        name: dict(value, enabled=True, methods=["*"]) for name, value in TYPE_DEFAULTS.items()
    }
    if set(common) - {"types"}:
        raise ValueError("common supports only canonical common.types policies")
    for name, entry in object_field(common, "types").items():
        if is_table_container(name):
            raise ValueError(
                f"common.types.{name} is a table conversion; container aliases are not supported"
            )
        if not re.fullmatch(r"Q[A-Za-z0-9_]+", name):
            raise ValueError(f"invalid Qt type key: {name}")
        if not isinstance(entry, dict):
            raise ValueError(f"invalid common.types.{name} policy")
        policy = cast(JsonObject, entry)
        if set(policy) - {"alias", "enabled", "methods", "metamethods"}:
            raise ValueError(f"invalid common.types.{name} policy")
        raw.setdefault(
            name, {"alias": name, "enabled": True, "methods": ["*"], "kind": "qt"}
        ).update(policy)
        for key, target in object_field(policy, "metamethods").items():
            if not re.fullmatch(r"__[a-z_]+", key) or not isinstance(target, str):
                raise ValueError(f"invalid common.types.{name}.metamethods entry")
    result: dict[str, CommonTypePolicy] = {}
    aliases: set[str] = set()
    for name, policy in raw.items():
        alias = policy["alias"]
        enabled = policy["enabled"]
        methods = policy["methods"]
        if (
            not isinstance(alias, str)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", alias)
            or alias in KEYWORDS | {qt_namespace(config), "_G"}
            or alias in aliases
        ):
            raise ValueError(f"invalid or duplicate common type alias: {alias}")
        if not isinstance(enabled, bool) or not isinstance(methods, list):
            raise ValueError(f"invalid common.types.{name} capabilities")
        checked_methods: list[str] = []
        for method in cast(list[object], methods):
            if not isinstance(method, str):
                raise ValueError(f"invalid common.types.{name}.methods entry")
            checked_methods.append(method)
        aliases.add(alias)
        result[name] = {
            "alias": alias,
            "kind": str(policy["kind"]),
            "enabled": enabled,
            "methods": checked_methods,
        }
    return result
