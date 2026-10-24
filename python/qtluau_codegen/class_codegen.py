# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Render methods and properties with explicit C++ access strategies."""

from __future__ import annotations

import fnmatch
import re

from .exclusions import excluded_method
from .member_scan import Members
from .models import JsonObject, NativeMethod, object_list_field, string_list_field
from .type_mapping import mapped_type


def normalized(name: str, arguments: list[str]) -> str:
    """Normalize a method name and parameter list for metadata matching."""
    return name + "(" + ",".join(re.sub(r"\bconst\b|\s|&", "", a) for a in arguments) + ")"


def render_members(
    native: str,
    wrapper: str,
    record: JsonObject,
    rule: JsonObject,
    members: Members,
    excluded: list[str],
    helper_name: str,
) -> tuple[list[str], list[str], list[JsonObject], list[JsonObject]]:
    """Render selected QObject members with the configured access strategy."""
    included = string_list_field(rule, "include", ["*"])
    omitted = string_list_field(rule, "exclude")

    def member_selected(name: str) -> bool:
        """Check a member against the configured include and exclude patterns."""
        return any(fnmatch.fnmatchcase(name, p) for p in included) and not any(
            fnmatch.fnmatchcase(name, p) for p in omitted
        )

    context = string_list_field(rule, "context")
    if context and rule.get("binding") != "functions":
        raise ValueError("context is available only for function bindings")
    if any(re.sub(r"\s", "", typ) not in {"QObject*", "constQObject*"} for typ in context):
        raise ValueError("context arguments must be QObject* or const QObject*")
    access_value: object = rule.get("access", ["public"])
    access = (
        [access_value]
        if isinstance(access_value, str)
        else string_list_field(rule, "access", ["public"])
    )
    if not access or set(access) - {"public", "protected", "private"}:
        raise ValueError("access must select public, protected and/or private")
    if "methods" in rule:
        raise ValueError("Use access and members instead of the obsolete methods selector")
    categories = string_list_field(rule, "members", ["methods", "properties", "fields"])
    if set(categories) - {"methods", "properties", "fields"}:
        raise ValueError("members must select methods, properties and/or fields")
    strategy = rule.get("non_public", "metaobject")
    if strategy not in {"metaobject", "friend"}:
        raise ValueError("non_public must be metaobject or friend")
    meta_methods: dict[str, JsonObject] = {}
    for method in [*object_list_field(record, "slots"), *object_list_field(record, "methods")]:
        args = [str(a["type"]) for a in object_list_field(method, "arguments")]
        meta_methods[normalized(method["name"], args)] = method
    signals = {
        normalized(s["name"], [str(a["type"]) for a in object_list_field(s, "arguments")])
        for s in object_list_field(record, "signals")
    }
    qt_properties = (
        object_list_field(record, "properties")
        if "properties" in categories and "public" in access
        else []
    )
    property_names = {p["name"] for p in qt_properties}
    methods_metadata: list[JsonObject] = []
    properties_metadata: list[JsonObject] = []
    registration: list[str] = []
    accessor = f"BindingAccess<{native}>" if strategy == "friend" else helper_name
    helpers: list[str] = [("template<> " if strategy == "friend" else "") + f"struct {accessor} {{"]
    functions = rule.get("binding") == "functions"
    capture = f"self = {wrapper}(object)" + "".join(
        f", context{i} = QPointer<QObject>(const_cast<QObject*>(context{i}))"
        for i in range(len(context))
    )
    groups: dict[str, list[str]] = {}
    for index, method in enumerate(members["methods"] if "methods" in categories else []):
        name = method["name"]
        signature = (
            name + "(" + ",".join(method["args"]) + ")" + (" const" if method["const"] else "")
        )
        visibility = members["access"][signature]
        meta = meta_methods.get(normalized(name, method["args"]))
        if (
            not member_selected(name)
            or visibility not in access
            or normalized(name, method["args"]) in signals
            or name in property_names
            or name.startswith("operator")
        ):
            continue
        if excluded_method(excluded, native, name, method["args"]):
            continue
        use_meta = visibility != "public" and strategy == "metaobject"
        if use_meta and meta is None:
            raise ValueError(
                f"{native}::{name} is {visibility}; use non_public=friend and friend qtluau::BindingAccess<{native}>, or expose a Qt slot/invokable"
            )
        selected: NativeMethod = method.copy()
        if use_meta and meta is not None:
            selected["result"] = meta["returnType"]
            selected["args"] = [str(a["type"]) for a in object_list_field(meta, "arguments")]
        native_args = list(selected["args"])
        if [re.sub(r"\s", "", typ) for typ in native_args[: len(context)]] != [
            re.sub(r"\s", "", typ) for typ in context
        ]:
            raise ValueError(f"Context argument prefix mismatch: {native}::{name}")
        selected["args"] = native_args[len(context) :]
        types = [mapped_type(selected["result"], True), *[mapped_type(a) for a in selected["args"]]]
        if not all(types) or selected["variadic"] or (use_meta and len(native_args) > 10):
            raise ValueError(
                f"Unsupported member signature: {native}::{name}; exclude it explicitly"
            )
        mapped = [t for t in types if t is not None]
        params = [f"{t[0]} arg{i}" for i, t in enumerate(mapped[1:])]
        if "qtToLua" in mapped[0][2]:
            params.append("lua_State *L")
        body = [
            f"auto *native = qobject_cast<{native}*>(self.get());",
            'if (!native) throw std::runtime_error("Native object type mismatch");',
        ]
        values = [f"context{i}.data()" for i in range(len(context))] + [
            t[2].format(expr=f"arg{i}") for i, t in enumerate(mapped[1:])
        ]
        body.extend(
            f'if (context{i}.isNull()) throw std::runtime_error("Binding context has been deleted");'
            for i in range(len(context))
        )
        if use_meta:
            for i, (typ, value) in enumerate(zip(native_args, values, strict=True)):
                body.append(f"{typ} value{i} = {value};")
            slot_signature = name + "(" + ",".join(native_args) + ")"
            body.extend(
                [
                    f'const int index = native->metaObject()->indexOfMethod("{slot_signature}");',
                    'if (index < 0) throw std::runtime_error("Meta-method not found");',
                ]
            )
            invocation = ["native", "Qt::DirectConnection"]
            if selected["result"] != "void":
                body.append(f"{selected['result']} result{{}};")
                invocation.append(f'QGenericReturnArgument("{selected["result"]}", &result)')
            invocation.extend(
                f'QGenericArgument("{typ}", &value{i})' for i, typ in enumerate(native_args)
            )
            body.append(
                f'if (!native->metaObject()->method(index).invoke({", ".join(invocation)})) throw std::runtime_error("Meta-method invocation failed");'
            )
            expression = "result"
        else:
            helper_params = ", ".join(f"{typ} a{i}" for i, typ in enumerate(native_args))
            cast = f"{selected['result']} ({native}::*)({', '.join(native_args)})" + (
                " const" if selected["const"] else ""
            )
            call = f"(object.*static_cast<{cast}>(&{native}::{name}))({', '.join(f'a{i}' for i in range(len(native_args)))})"
            helpers.append(
                f"static {selected['result']} call{index}({native} &object{', ' if helper_params else ''}{helper_params}) {{ return {call}; }}"
            )
            args = ", ".join(values)
            expression = f"{accessor}::call{index}(*native{', ' if args else ''}{args})"
        statement = mapped[0][2].format(expr=expression)
        if selected["result"] != "void":
            body.append("return " + statement + ";")
        elif not use_meta:
            body.append(statement + ";")
        closure = (
            f"[{capture}]({', '.join(params)})"
            if functions
            else f"[]({wrapper} &self{', ' if params else ''}{', '.join(params)})"
        )
        groups.setdefault(name, []).append(f"{closure} {{ {' '.join(body)} }}")
        methods_metadata.append(
            {"name": name, "parameters": [t[1] for t in mapped[1:]], "result": mapped[0][1]}
        )
    for name, overloads in groups.items():
        registration.append(f'cls.addFunction("{name}", {", ".join(overloads)});')
    properties: list[JsonObject] = []
    # Q_PROPERTY is a public meta-object contract, independent of accessor visibility.
    if "public" in access:
        properties.extend(
            {
                "name": p["name"],
                "type": p["type"],
                "readonly": not bool(p.get("write")),
                "meta": True,
            }
            for p in qt_properties
            if member_selected(p["name"]) and (p.get("read") or p.get("member"))
        )
    if "fields" in categories:
        for field in members["fields"]:
            if (
                not member_selected(field["name"])
                or field["name"] in property_names
                or field["access"] not in access
            ):
                continue
            if field["access"] != "public" and strategy != "friend":
                raise ValueError(f"{native}::{field['name']} requires non_public=friend")
            properties.append(dict(field, meta=False))
    for index, prop in enumerate(properties):
        name: str = prop["name"]
        if excluded_method(excluded, native, name):
            continue
        if name in groups:
            raise ValueError(f"Method/property name collision: {native}::{name}")
        typ: str = prop["type"]
        result = mapped_type(typ, True)
        argument = mapped_type(typ)
        if result is None or argument is None:
            raise ValueError(f"Unsupported property: {native}::{name} ({typ})")
        state = ", lua_State *L" if "qtToLua" in result[2] else ""
        if prop["meta"]:
            value = f'self.get()->property("{name}").value<{typ}>()'
            assign = f'if (!self.get()->setProperty("{name}", QVariant::fromValue({argument[2].format(expr="value")}))) throw std::runtime_error("Property write failed");'
        else:
            helpers.append(f"static auto get{index}({native} &object) {{ return object.{name}; }}")
            value = f"{accessor}::get{index}(*qobject_cast<{native}*>(self.get()))"
            helpers.append(
                f"static void set{index}({native} &object, {typ} value) {{ object.{name} = value; }}"
                if not prop["readonly"]
                else ""
            )
            assign = f"{accessor}::set{index}(*qobject_cast<{native}*>(self.get()), {argument[2].format(expr='value')});"
        getter = f"[]({wrapper} &self{state}) {{ return {result[2].format(expr=value)}; }}"
        setter = (
            "" if prop["readonly"] else f", []({wrapper} &self, {argument[0]} value) {{ {assign} }}"
        )
        registration.append(f'cls.addProperty("{name}", {getter}{setter});')
        properties_metadata.append(
            {"name": name, "type": result[1], "readonly": bool(prop["readonly"])}
        )
    helpers.append("};")
    return registration, helpers, methods_metadata, properties_metadata
