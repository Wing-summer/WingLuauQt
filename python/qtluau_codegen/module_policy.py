# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Resolve module exposure without changing its namespace or builtin name."""

from .models import JsonObject, object_field


def requires_module(config: JsonObject, module: str) -> bool:
    """Return whether a named module must be imported; globals are the default."""
    if not module:
        return False
    policy = object_field(object_field(config, "modules"), module)
    required = policy.get("require", False)
    if not isinstance(required, bool):
        raise ValueError(f"modules.{module}.require must be boolean")
    return required
