# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Derive binding metadata from C++ support declarations and the active Qt SDK."""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Sequence
from typing import cast

from .assets import support_root
from .discovery import scan
from .models import (
    ClassDefinition,
    JsonObject,
    Method,
    NativeMethod,
    Parameters,
    object_field,
    string_list_field,
)
from .native_values import value_methods
from .type_mapping import mapped_type
from .wrapper_contract import wrapper_methods


def sequence(value: object, label: str) -> Sequence[object]:
    """Validate catalog sequences and return a typed list of elements."""
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array")
    return cast(Sequence[object], value)


def parameters(value: object) -> Parameters:
    """Convert catalog parameter entries into named typed parameters."""
    result: Parameters = []
    for entry in sequence(value, "parameters"):
        pair = sequence(entry, "parameter")
        if len(pair) != 2 or not isinstance(pair[0], str) or not isinstance(pair[1], str):
            raise ValueError("parameter must contain a name and type string")
        result.append((pair[0], pair[1]))
    return result


def load_class(raw: JsonObject) -> ClassDefinition:
    # Deserialize at the boundary; do not coerce arbitrary JSON into API strings.
    """Validate and normalize a class catalog definition."""
    methods: list[Method] = []
    for entry in sequence(raw.get("methods", []), "methods"):
        method = sequence(entry, "method")
        if len(method) != 3 or not isinstance(method[0], str) or not isinstance(method[2], str):
            raise ValueError("method must contain a name, parameters and result type")
        methods.append((method[0], parameters(method[1]), method[2]))
    constructors = [
        parameters(entry) for entry in sequence(raw.get("constructors", []), "constructors")
    ]
    base: object = raw.get("base")
    if base is not None and not isinstance(base, str):
        raise ValueError("base must be a type name or null")
    return {"base": base, "methods": methods, "constructors": constructors}


def _ancestors(name: str, seen: set[str] | None = None) -> set[str]:
    """Return SDK ancestry, retaining the concrete class in the result."""
    seen = set() if seen is None else seen
    if name in seen:
        return seen
    seen.add(name)
    record = _native.get(name)
    if record is not None:
        for base in record["bases"]:
            _ancestors(base, seen)
    return seen


def _constructors(name: str) -> list[Parameters]:
    """Infer supported empty/text widget or numeric native value constructors."""
    record = _native.get(name)
    if record is None or record["abstract"]:
        return []
    result: list[Parameters] = []
    for args in record.get("constructors", []):
        if not args:
            signature: Parameters = []
        elif (
            name in WIDGET_NATIVE_NAMES
            and len(args) == 1
            and "".join(args[0].split()) in {"QString", "constQString&"}
        ):
            signature = [("text", "string")]
        elif name not in WIDGET_NATIVE_NAMES and all(arg == "int" for arg in args):
            signature = [(f"arg{i}", "number") for i in range(len(args))]
        else:
            continue
        if signature not in result:
            result.append(signature)
    return result


_root = support_root()
_defaults: JsonObject = json.loads((_root / "config/bindings.json").read_text())
_wrapper_methods = wrapper_methods()
_native, _flags = scan(["QtCore", "QtGui", "QtWidgets"])
_generic_methods = _wrapper_methods["QtWidgetRef"]
_default_blacklist = string_list_field(
    object_field(object_field(_defaults, "qt"), "discovery"), "blacklist"
)
_safety_exclusions = set(string_list_field(object_field(_defaults, "exclude"), "classes"))
WIDGET_NATIVE_NAMES = {
    name
    for name in _native
    if _ancestors(name) & {"QWidget", "QLayout"}
    and not (_ancestors(name) & _safety_exclusions)
    and not any(fnmatch.fnmatchcase(name, pattern) for pattern in _default_blacklist)
}
WIDGETS: dict[str, ClassDefinition] = {}
for _name in sorted(
    WIDGET_NATIVE_NAMES, key=lambda name: (name not in {"QWidget", "QLayout"}, name)
):
    _base = (
        None
        if _name in {"QWidget", "QLayout"}
        else ("QLayout" if "QLayout" in _ancestors(_name) else "QWidget")
    )
    _methods = list(_wrapper_methods["QtWidgetRef"].values()) if _name == "QWidget" else []
    WIDGETS[_name] = {"base": _base, "methods": _methods, "constructors": _constructors(_name)}
for _name in sorted(WIDGET_NATIVE_NAMES):
    if "QWidget" in _ancestors(_name):
        WIDGETS["QWidget"]["methods"].append(
            ("findChild" + _name[1:], [("objectName", "string")], "_qt_" + _name)
        )

OBJECT_TYPE: ClassDefinition = {
    "base": None,
    "methods": list(_wrapper_methods["QObjectRef"].values()),
    "constructors": [],
}
OBJECT_POINTERS = {name for name in _native if "QObject" in _ancestors(name)}
LAYOUT_POINTERS = {name for name in OBJECT_POINTERS if "QLayout" in _ancestors(name)}
WIDGET_POINTERS = {name for name in OBJECT_POINTERS if "QWidget" in _ancestors(name)}

# Default aliases and safety rules are ordinary shipped policy, not API metadata.
EXCLUDED_ALWAYS = set(string_list_field(object_field(_defaults, "exclude"), "classes"))
DEFAULT_EXCLUDED_MEMBERS = string_list_field(object_field(_defaults, "exclude"), "members")
DEFAULT_WIDGETS = [name for name, definition in WIDGETS.items() if definition["constructors"]]
_common_types = object_field(object_field(_defaults, "common"), "types")
BACKENDS: dict[str, dict[str, str]] = {
    native: {"cpp_type": f"QtValueRef<{native}>"} for native in _common_types if native in _native
}
_variant_header = (_root / "include/qtluau/value_conversion.hpp").read_text()
_variant_match = re.search(r"struct (\w+) \{\s*(Q\w+) value;", _variant_header)
if _variant_match is None:
    raise ValueError("Missing native variant wrapper declaration")
_variant_wrapper, _variant_native = _variant_match.groups()
BACKENDS[_variant_native] = {"cpp_type": _variant_wrapper}
VARIANT_METHODS = {name: method[2] for name, method in _wrapper_methods[_variant_wrapper].items()}
TYPE_DEFAULTS: dict[str, dict[str, str]] = {
    native: {
        "alias": entry["alias"],
        "kind": "variant" if native == _variant_native else "userdata",
    }
    for native, entry in object_field(object_field(_defaults, "common"), "types").items()
}
COMMON_NATIVE_METHODS = {
    name: value_methods(name, _native[name])
    for name in _common_types
    if name in _native and name != _variant_native
}
COMMON_ADAPTERS: dict[str, ClassDefinition] = {
    native: {
        "base": None,
        "methods": [method.definition(native) for method in methods],
        "constructors": [[], [("value", "string")], [("value", "$self")]],
    }
    for native, methods in COMMON_NATIVE_METHODS.items()
}
COMMON_CONSTRUCTOR_SIGNATURES = {native: native for native in COMMON_ADAPTERS}
VALUE_TYPES: dict[str, ClassDefinition] = {}
VALUE_NATIVE_METHODS: dict[str, list[tuple[NativeMethod, int]]] = {}
for _name, _record in _native.items():
    _mapping = mapped_type(_name)
    if _mapping is None or _mapping[:2] != (_name, "_qt_" + _name):
        continue
    BACKENDS[_name] = {"cpp_type": _name}
    _value_methods: list[Method] = []
    _native_methods: list[tuple[NativeMethod, int]] = []
    for _method in _record["methods"]:
        if (
            _method["static"]
            or _method["deprecated"]
            or _method["variadic"]
            or not _method["name"].isidentifier()
        ):
            continue
        _return = mapped_type(_method["result"], True)
        if _return is None:
            continue
        for _count in range(
            _method.get("minimum_args", len(_method["args"])), len(_method["args"]) + 1
        ):
            _args = [mapped_type(arg) for arg in _method["args"][:_count]]
            if any(arg is None for arg in _args):
                continue
            _value_methods.append(
                (
                    _method["name"],
                    [(f"arg{i}", arg[1]) for i, arg in enumerate(_args) if arg is not None],
                    _return[1],
                )
            )
            _native_methods.append((_method, _count))
    VALUE_TYPES[_name] = {
        "base": None,
        "methods": _value_methods,
        "constructors": _constructors(_name),
    }
    VALUE_NATIVE_METHODS[_name] = _native_methods
for _name in WIDGETS:
    BACKENDS[_name] = {
        "cpp_type": ("Qt" + _name[1:] + "Ref")
        if _name in {"QWidget", "QLayout"}
        else (
            f"QtTypedLayoutRef<{_name}>"
            if "QLayout" in _ancestors(_name)
            else f"QtTypedWidgetRef<{_name}>"
        )
    }
