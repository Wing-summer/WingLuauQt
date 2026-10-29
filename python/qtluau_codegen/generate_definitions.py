#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Emit Luau LSP definitions from the exact configured binding surface.

Only methods implemented by this runtime adapter are emitted. The small IR
extension supports generic generated wrappers, including variadic signatures;
variadics are emitted only when explicitly present in IR metadata.
"""

import argparse
import copy
import fnmatch
import json
import pathlib
import re
import sys
from typing import cast

from .catalog import (
    COMMON_ADAPTERS,
    COMMON_CONSTRUCTOR_SIGNATURES,
    DEFAULT_WIDGETS,
    EXCLUDED_ALWAYS,
    OBJECT_TYPE,
    TYPE_DEFAULTS,
    VALUE_TYPES,
    VARIANT_METHODS,
    WIDGETS,
    load_class,
)
from .declaration_tables import merge_namespace_declarations
from .extensions import definitions as extension_definitions
from .function_naming import rename_declarations
from .models import (
    ClassDefinition,
    JsonObject,
    Parameters,
    object_field,
    object_list_field,
    string_list_field,
)
from .module_policy import qt_namespace
from .type_policy import common_types


def load_config(path: pathlib.Path) -> JsonObject:
    """Read a JSON policy file and return its configuration record."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_names(values: object) -> list[str]:
    """Read configured type selections as a list of names."""
    if not isinstance(values, list):
        raise ValueError("expected a JSON array of strings")
    result: list[str] = []
    for value in cast(list[object], values):
        if not isinstance(value, str):
            raise ValueError("expected a JSON array of strings")
        result.append(value)
    return result


def constructor_type(name: str, definition: ClassDefinition, string_alias: str = "ustring") -> str:
    """Render constructor overload types using the configured string alias."""
    signatures: list[str] = []
    for ctor in definition["constructors"]:
        args = ", ".join(
            f"{n}: {'string | ' + string_alias if t == 'string' else t}" for n, t in ctor
        )
        signatures.append(f"(({args}) -> _qt_{name})")
    return " & ".join(signatures) if signatures else "{}"


def class_def(name: str, metadata: ClassDefinition) -> str:
    """Render a native class surface as Luau declarations."""
    base = metadata.get("base")
    parent = f" extends _qt_{base}" if base else ""
    lines = [f"declare extern type _qt_{name}{parent} with"]
    # Method property intersections preserve overloads, including identical arity.
    groups: dict[str, list[str]] = {}
    for method, params, result in metadata["methods"]:
        args: list[str] = []
        for n, t in params:
            args.append(f"{n}: {t}")
        receiver = f"self: _qt_{name}" + (", " if args else "")
        groups.setdefault(method, []).append(f"(({receiver}{', '.join(args)}) -> {result})")
    for method, signatures in groups.items():
        lines.append(f"    {method}: " + " & ".join(dict.fromkeys(signatures)))
    lines.append("end")
    return "\n".join(lines)


def member_excluded(excluded: set[str], class_name: str, member_name: str) -> bool:
    """Check whether a member is removed by class or signature policy."""
    prefix = f"{class_name}::{member_name}"
    if prefix in excluded:
        return True
    # This wrapper metadata currently describes one exposed signature per method.
    # Any signature-specific exclusion with the same canonical method name excludes
    # that normalized wrapper member. The generic header scanner handles exact overloads.
    return any(entry.startswith(prefix + "(") for entry in excluded)


def constructor_excluded(
    excluded: set[str], class_name: str, ctor: Parameters | None = None
) -> bool:
    """Check whether constructor policy removes a native signature."""
    if f"{class_name}::new" in excluded:
        return True
    if ctor is None:
        return False
    cpp_types = {
        "string": "QString",
        "boolean": "bool",
        "number": "int",
        "_qt_QWidget": "QWidget*",
        "_qt_QLayout": "QLayout*",
    }
    args = ",".join(cpp_types.get(arg_type, arg_type.rstrip("?")) for _, arg_type in ctor)
    return f"{class_name}::new({args})" in excluded


def emit_ir_function(fn: JsonObject) -> str:
    """Render one function descriptor as a Luau declaration."""
    name = fn["name"]
    params = object_list_field(fn, "parameters")
    args = [f"{p['name']}: {p['type']}" for p in params]
    variadic = fn.get("variadic")
    if variadic is not None:
        if not isinstance(variadic, dict) or not isinstance(
            cast(JsonObject, variadic).get("type"), str
        ):
            raise ValueError(f"invalid variadic metadata for {name}")
        args.append(f"...: {variadic['type']}")
    returns = string_list_field(fn, "returns")
    if len(returns) == 0:
        ret = "()"
    elif len(returns) == 1:
        ret = returns[0]
    else:
        ret = "(" + ", ".join(returns) + ")"
    return f"declare function {name}({', '.join(args)}): {ret}"


def generate(
    config: JsonObject, out_dir: pathlib.Path, config_dir: pathlib.Path | None = None
) -> None:
    """Write common, Qt and combined declarations from a resolved policy."""
    if config.get("schema_version", 1) != 1:
        raise ValueError("unsupported schema_version; expected 1")
    lsp = object_field(config, "lsp")
    if lsp.get("server", "luau-lsp") != "luau-lsp" or lsp.get("syntax", "luau") != "luau":
        raise ValueError(
            "Definition output supports luau-lsp / Luau syntax; LuaLS annotations are not compatible"
        )
    if "_generated" not in config or ("extensions" in config and "_extensions" not in config):
        import tempfile

        from .qt_pipeline import emit

        with tempfile.TemporaryDirectory(prefix="qtluau-policy-") as temporary:
            config = emit(config, pathlib.Path(temporary), config_dir)
    available = copy.deepcopy(WIDGETS)
    for name, raw_definition in object_field(object_field(config, "_generated"), "types").items():
        definition = load_class(raw_definition)
        if name in available:
            available[name]["methods"].extend(definition["methods"])
        else:
            available[name] = definition
    value_types = VALUE_TYPES
    available.update(value_types)
    available["QObject"] = OBJECT_TYPE
    policies = common_types(config)
    string_alias = policies["QString"]["alias"]
    qt = object_field(config, "qt")
    namespace = qt_namespace(config)
    widgets = object_field(qt, "widgets")
    requested = list_names(widgets.get("include", DEFAULT_WIDGETS)) + list_names(
        string_list_field(widgets, "extra_types")
    )
    requested += [
        name for name, policy in policies.items() if policy["kind"] == "qt" and policy["enabled"]
    ]
    requested = [
        name for name in requested if name not in policies or policies[name]["kind"] == "qt"
    ]
    excluded = (
        EXCLUDED_ALWAYS
        | set(list_names(string_list_field(widgets, "exclude")))
        | set(list_names(string_list_field(object_field(config, "exclude"), "classes")))
    )
    excluded |= {name for name, policy in policies.items() if not policy["enabled"]}
    excluded |= {
        name
        for name in available
        if any(fnmatch.fnmatchcase(name, pattern) for pattern in excluded)
    }
    while True:
        descendants = {
            name for name, definition in available.items() if definition.get("base") in excluded
        }
        if descendants <= excluded:
            break
        excluded |= descendants
    unknown = sorted({n for n in requested if n not in available and n not in excluded})
    if unknown:
        raise ValueError(
            "no Definition/runtime metadata for configured Qt type(s): " + ", ".join(unknown)
        )
    selected = list(dict.fromkeys(n for n in requested if n not in excluded and n in available))
    excluded_members = set(
        list_names(string_list_field(object_field(config, "exclude"), "members"))
    )
    metadata = {name: copy.deepcopy(definition) for name, definition in available.items()}
    child_finder_types = {
        method: result.removeprefix("_qt_")
        for method, _, result in WIDGETS["QWidget"]["methods"]
        if method.startswith("findChild")
        and method != "findChildWidget"
        and result.startswith("_qt_")
    }
    metadata["QWidget"]["methods"] = [
        method
        for method in metadata["QWidget"]["methods"]
        if not (method[0] in child_finder_types and child_finder_types[method[0]] not in selected)
    ]
    for name, definition in metadata.items():
        definition["methods"] = [
            m
            for m in definition["methods"]
            if not member_excluded(excluded_members, name, m[0])
            and (
                name not in policies
                or "*" in policies[name]["methods"]
                or m[0] in policies[name]["methods"]
            )
            and (
                name not in policies
                or not member_excluded(excluded_members, policies[name]["alias"], m[0])
            )
            and not any("_qt_" + e in str(m) for e in excluded)
        ]
        definition["constructors"] = [
            ctor
            for ctor in definition["constructors"]
            if not constructor_excluded(excluded_members, name, ctor)
        ]
    if (
        widgets.get("expose_qwidget_base", True)
        and "QWidget" not in selected
        and "QWidget" not in excluded
    ):
        selected.insert(0, "QWidget")
    # Public type set includes only selected classes and their transitive bases.
    # The declaration closure additionally includes types used in method signatures,
    # so .ui child lookup can infer its concrete return type without exporting every
    # widget constructor under qt.
    exported = set(selected) | (set(value_types) - excluded)
    base_todo = list(selected)
    while base_todo:
        item = base_todo.pop()
        base = metadata[item].get("base")
        if base and base not in exported:
            exported.add(base)
            base_todo.append(base)
    if "QWidget" in exported or any(
        x in exported for x in ("QVBoxLayout", "QHBoxLayout", "QGridLayout")
    ):
        exported.add("QLayout")

    closure = set(exported)
    type_ref = re.compile(r"_qt_([A-Za-z_][A-Za-z0-9_]*)")
    pending = list(closure)
    while pending:
        item = pending.pop()
        definition = metadata[item]
        signature_types = [definition.get("base")]
        signature_types.extend(t for _, _, t in definition["methods"])
        for _, params, _ in definition["methods"]:
            signature_types.extend(t for _, t in params)
        for ctor in definition["constructors"]:
            signature_types.extend(t for _, t in ctor)
        for signature in signature_types:
            if not isinstance(signature, str):
                continue
            for referenced in type_ref.findall(signature):
                if referenced not in metadata:
                    raise ValueError(
                        f"{item} references a type without Definition metadata: {referenced}"
                    )
                if referenced not in closure:
                    closure.add(referenced)
                    pending.append(referenced)

    out_dir.mkdir(parents=True, exist_ok=True)
    builtins: list[str] = []
    # Class tables are exposed only as fields of qt. Internal type names are prefixed to avoid
    # declaring global runtime constructors such as QPushButton.
    ordered_types: list[str] = []

    def order_type(name: str) -> None:
        """Order parent types before dependent child declarations."""
        if name in ordered_types:
            return
        base = metadata[name].get("base")
        if base in closure:
            order_type(base)
        ordered_types.append(name)

    for name in sorted(closure):
        order_type(name)
    for name in ordered_types:
        builtins.append(class_def(name, metadata[name]))
    common_lines: list[str] = []
    lines = [f"declare {namespace}: {{"]
    for canonical, adapter in COMMON_ADAPTERS.items():
        policy = policies[canonical]
        alias = policy["alias"]
        enabled = policy["enabled"] and canonical not in excluded
        type_name = alias if enabled else "_qtluau_" + TYPE_DEFAULTS[canonical]["alias"]
        common_definition = [f"declare extern type {type_name} with"]
        for method, params, result in adapter["methods"]:
            if (
                ("*" not in policy["methods"] and method not in policy["methods"])
                or member_excluded(excluded_members, canonical, method)
                or member_excluded(excluded_members, alias, method)
            ):
                continue
            arguments = ", ".join(
                f"{name}: {kind.replace('$self', type_name)}" for name, kind in params
            )
            common_definition.append(
                f"    function {method}(self{', ' if arguments else ''}{arguments}): {result}"
            )
        common_definition.append("end")
        if enabled:
            constructors: list[str] = []
            for parameters in adapter["constructors"]:
                signature = COMMON_CONSTRUCTOR_SIGNATURES[canonical] if parameters else ""
                if (
                    f"{canonical}::new" in excluded_members
                    or f"{canonical}::new({signature})" in excluded_members
                ):
                    continue
                arguments = ", ".join(
                    f"{name}: {kind.replace('$self', type_name)}" for name, kind in parameters
                )
                constructors.append(f"(({arguments}) -> {type_name})")
            common_definition.append(
                f"\ndeclare {alias}: " + (" & ".join(constructors) if constructors else "{}")
            )
            lines.append(f"    {canonical}: typeof({alias}),")
        else:
            builtins = [
                re.sub(r"\b" + re.escape(alias) + r"\b", type_name, declaration)
                for declaration in builtins
            ]
        common_lines.append("\n".join(common_definition))
    variant_name = "_qtluau_QVariant"
    variant_methods = VARIANT_METHODS
    variant_lines = [f"declare extern type {variant_name} with"]
    variant_policy = policies["QVariant"]
    for method, result in variant_methods.items():
        if (
            ("*" in variant_policy["methods"] or method in variant_policy["methods"])
            and not member_excluded(excluded_members, "QVariant", method)
            and not member_excluded(excluded_members, variant_policy["alias"], method)
        ):
            variant_lines.append(f"    function {method}(self): {result}")
    variant_lines.append("end")
    common_lines.append("\n".join(variant_lines))
    if variant_policy["enabled"] and "QVariant" not in excluded:
        alias = variant_policy["alias"]
        signature = (
            "{}"
            if constructor_excluded(excluded_members, "QVariant")
            else (f"(() -> {variant_name}) & ((value: any, typeName: string?) -> {variant_name})")
        )
        common_lines.append(f"declare {alias}: {signature}")
        lines.append(f"    QVariant: typeof({alias}),")
    for canonical, policy in policies.items():
        if policy["kind"] == "qt" and policy["enabled"] and canonical not in excluded:
            if canonical not in metadata:
                raise ValueError(f"No binding metadata for alias {canonical}")
            common_lines.append(
                f"declare {policy['alias']}: {constructor_type(canonical, metadata[canonical], string_alias)}"
            )
    lines.append("    null: any,")
    for name in sorted(selected):
        lines.append(f"    {name}: {constructor_type(name, metadata[name], string_alias)},")
    # Base classes used by inheritance are addressable in qt, but types pulled in only
    # to describe a typed method result remain declaration-only until explicitly selected.
    for name in sorted(exported - set(selected)):
        if name not in excluded:
            lines.append(f"    {name}: {constructor_type(name, metadata[name], string_alias)},")
    ui_tools = object_field(qt, "ui_tools")
    if ui_tools.get("enabled", True):
        if "QWidget" not in closure:
            raise ValueError(
                "qt.ui_tools.enabled requires QWidget in the selected/dependency type set"
            )
        lines.append("    loadUiWidgetXml: (xml: string) -> _qt_QWidget,")
        lines.append("    loadUiWidgetFile: (path: string) -> _qt_QWidget,")
    lines[-1] = lines[-1].rstrip(",")
    lines.append("}")
    (out_dir / "common.d.luau").write_text("\n\n".join(common_lines) + "\n", encoding="utf-8")
    (out_dir / "qt.d.luau").write_text(
        "\n\n".join(builtins) + "\n\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )

    functions = object_list_field(object_field(config, "ir"), "functions")
    generated_functions = out_dir / "generated_functions.d.luau"
    if functions:
        generated_functions.write_text(
            "\n".join(emit_ir_function(fn) for fn in functions) + "\n", encoding="utf-8"
        )
    elif generated_functions.exists():
        generated_functions.unlink()
    combined = (
        (out_dir / "common.d.luau").read_text(encoding="utf-8")
        + "\n"
        + (out_dir / "qt.d.luau").read_text(encoding="utf-8")
    )
    if functions:
        combined += "\n" + generated_functions.read_text(encoding="utf-8")
    extension_text = extension_definitions(object_list_field(config, "_extensions"))
    (out_dir / "extensions.d.luau").write_text(extension_text, encoding="utf-8")
    combined = merge_namespace_declarations(combined + "\n" + extension_text)
    (out_dir / "qtluau.d.luau").write_text(combined, encoding="utf-8")
    for path in out_dir.glob("*.d.luau"):
        path.write_text(rename_declarations(config, path.read_text()), encoding="utf-8")
    print(f"Generated definitions into {out_dir} (widgets: {', '.join(selected)})")


def main() -> int:
    """Parse declaration-generation arguments and return the process status."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, type=pathlib.Path)
    parser.add_argument("--out", required=True, type=pathlib.Path)
    args = parser.parse_args()
    try:
        generate(load_config(args.config), args.out, args.config.resolve().parent)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"definition generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
