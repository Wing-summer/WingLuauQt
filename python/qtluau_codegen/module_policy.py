# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Resolve module exposure without changing its namespace or builtin name."""

import re

from .models import JsonObject, object_field

KEYWORDS = set(
    "and break do else elseif end false for function if in local nil not or repeat return then true until while".split()
)


def requires_module(config: JsonObject, module: str) -> bool:
    """Return whether a named module must be imported; globals are the default."""
    if not module:
        return False
    policy = object_field(object_field(config, "modules"), module)
    required = policy.get("require", False)
    if not isinstance(required, bool):
        raise ValueError(f"modules.{module}.require must be boolean")
    return required


def qt_namespace(config: JsonObject) -> str:
    """Return the validated public Qt module name, independently of C++ namespaces."""
    name = object_field(config, "qt").get("namespace", "qt")
    if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name, re.ASCII)
            or name in KEYWORDS | {"_G"}):
        raise ValueError("qt.namespace must be a nonreserved Luau identifier")
    return name
