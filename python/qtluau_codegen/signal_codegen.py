# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate queued typed signal connectors from SDK method annotations."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .function_naming import snake_case

if TYPE_CHECKING:
    from .framework_bindings import SdkBindings


def signal_connector(generator: SdkBindings, native: str) -> tuple[list[str], list[str]]:
    """Emit native pointer-checked connections, snapshots and callback signatures."""
    code = [f"bool connect_sdk_{native}(QObject *object, const QByteArray &signature, const luabridge::LuaRef &callback) {{",
            f"auto *sender = qobject_cast<{native} *>(object); if (!sender) {{ return false; }}"]
    signatures: list[str] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for method in generator.methods(native):
        if not method.get("signal") or not generator.method_allowed(native, method):
            continue
        key = (method["name"], tuple(method["args"]))
        if key in seen:
            continue
        seen.add(key)
        owner = method["owner"]
        conversions = [generator.conversion(spelling, owner, True) for spelling in method["args"]]
        captures: list[str] = []
        values: list[str] = []
        supported = True
        for index, (spelling, converted) in enumerate(zip(method["args"], conversions)):
            if converted is None or ("&" in spelling and not spelling.startswith("const ")):
                supported = False
                break
            if "*" in spelling:
                bare = re.sub(r"\bconst\b|[ *]", "", spelling)
                if not generator.object_type(bare):
                    supported = False
                    break
                captures.append(f"value{index} = QPointer<{bare}>(arg{index})")
                value = f"value{index}.data()"
            else:
                captures.append(f"value{index} = arg{index}")
                value = f"value{index}"
            values.append("luabridge::LuaRef(L, " + converted.write.format(expr=value) + ")")
        if not supported:
            generator.rejected.append({"class": native, "method": method["name"],
                                       "reason": "unsupported signal snapshot", "kind": "signal"})
            continue
        pointer = f"static_cast<void ({owner}::*)({', '.join(method['args'])})>(&{owner}::{method['name']})"
        params = ", ".join(f"{spelling} arg{index}" for index, spelling in enumerate(method["args"]))
        code.extend([
            f"if (signature == QMetaMethod::fromSignal({pointer}).methodSignature()) {{",
            f"connectQueuedSignal(sender, {pointer}, callback, []({params}) -> LuaSignalArguments {{",
            "return [" + ", ".join(captures) + "](lua_State *L) -> std::vector<luabridge::LuaRef> { return {" + ", ".join(values) + "}; };",
            "}); return true; }",
        ])
        args = ", ".join(f"arg{index}: {value.lua}" for index, value in enumerate(conversions) if value is not None)
        for label in dict.fromkeys((snake_case(method["name"]), method["name"])):
            signatures.append(f'(self: _qt_{native}, signal: "{label}", callback: ({args}) -> ()) -> ()')
    code.append("return false; }")
    return code, signatures
