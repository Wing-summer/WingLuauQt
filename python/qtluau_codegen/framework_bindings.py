# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate optional Qt modules from SDK declarations and a type dependency closure."""

from __future__ import annotations

import fnmatch
import json
import pathlib
import re
from dataclasses import dataclass, replace
from typing import cast

from .assets import support_root
from .catalog import BACKENDS, NATIVE_CLASSES, TYPE_DEFAULTS, VALUE_TYPES, WIDGETS
from .discovery import SDK_CONTAINER_ALIASES, SDK_ENUMS, SDK_FLAGS, SDK_FUNCTIONS
from .exclusions import excluded_method
from .extensions import identifier, write
from .function_naming import snake_case
from .models import JsonObject, NativeMethod, object_field, object_list_field, string_list_field
from .module_policy import qt_namespace, requires_module
from .signal_codegen import signal_connector
from .type_mapping import mapped_type
from .type_policy import common_types


def text(parent: JsonObject, key: str, default: str = "") -> str:
    """Read a validated policy string."""
    value = parent.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


@dataclass(frozen=True)
class Conversion:
    """Describe one discovered native conversion and its generated Lua surface."""

    #: C++ lambda argument spelling.
    cpp: str
    #: Luau declaration spelling.
    lua: str
    #: Native argument conversion.
    read: str
    #: Lua return conversion.
    write: str
    #: Native dependencies selected by this conversion.
    dependencies: tuple[str, ...] = ()


class SdkBindings:
    """Resolve SDK signatures once for registration, definitions and reports."""

    def __init__(self, config: JsonObject) -> None:
        """Initialize generation policy without a maintained API member list."""
        self.config = config
        self.module = qt_namespace(config)
        self.policies = common_types(config)
        self.classes: set[str] = set()
        self.rejected: list[JsonObject] = []
        self.exclude = object_field(config, "exclude")
        self.members = string_list_field(self.exclude, "members")
        self.existing = set(BACKENDS) | set(VALUE_TYPES) | set(WIDGETS) | {"QObject"}
        self.string_type = self.common_type_name("QString")

    def common_type_name(self, native: str) -> str:
        """Resolve a common instance type without confusing constructor values with types."""
        policy = self.policies.get(native)
        if policy is None:
            return "_qt_" + native
        if policy["kind"] == "variant":
            return "_qtluau_" + native
        excluded = any(fnmatch.fnmatchcase(native, pattern)
                       for pattern in string_list_field(self.exclude, "classes"))
        if not policy["enabled"] or excluded:
            return "_qtluau_" + TYPE_DEFAULTS[native]["alias"]
        return policy["alias"]

    def adapter(self, native: str) -> JsonObject:
        """Read optional host factory, guard and call-adapter hooks."""
        return object_field(object_field(object_field(self.config, "sdk_bindings"),
                                         "class_adapters"), native)

    def methods(self, native: str, seen: set[str] | None = None) -> list[NativeMethod]:
        """Scan inherited public methods when requested, respecting C++ name hiding."""
        seen = set() if seen is None else seen
        if native in seen or native not in NATIVE_CLASSES:
            return []
        seen.add(native)
        record = NATIVE_CLASSES[native]
        result = list(record["methods"])
        if self.adapter(native).get("inherited_methods") or len(seen) > 1:
            own = {method["name"] for method in result}
            for base in record["bases"]:
                if base != "QObject":
                    result.extend(method for method in self.methods(base, seen)
                                  if method["name"] not in own or method["name"] in record.get("using_methods", []))
        return result

    def object_type(self, native: str, seen: set[str] | None = None) -> bool:
        """Determine QObject ancestry from the same SDK class records."""
        if native == "QObject":
            return True
        seen = set() if seen is None else seen
        if native in seen:
            return False
        seen.add(native)
        record = NATIVE_CLASSES.get(native)
        return record is not None and any(self.object_type(base, seen) for base in record["bases"])

    def allowed(self, native: str) -> bool:
        """Apply class exclusions and reject private/internal SDK declarations."""
        record = NATIVE_CLASSES.get(native)
        return (
            record is not None
            and not pathlib.Path(record["source"]).name.endswith("_p.h")
            and not any(
                fnmatch.fnmatchcase(native, pattern)
                for pattern in string_list_field(self.exclude, "classes")
            )
        )

    def enum_type(self, spelling: str, owner: str) -> str | None:
        """Resolve scoped and inherited enum spellings from discovered enum records."""
        if spelling in SDK_ENUMS:
            return spelling
        todo = [owner]
        seen: set[str] = set()
        while todo:
            name = todo.pop()
            if name in seen:
                continue
            seen.add(name)
            if name + "::" + spelling in SDK_ENUMS:
                return name + "::" + spelling
            record = NATIVE_CLASSES.get(name)
            if record is not None:
                todo.extend(record["bases"])
        return None

    def flags_type(self, spelling: str, owner: str) -> str | None:
        """Resolve a QFlags alias in its native class/base scope."""
        todo = [owner]
        seen: set[str] = set()
        if spelling in SDK_FLAGS:
            return SDK_FLAGS[spelling]
        if spelling.startswith("QFlags<"):
            return spelling
        while todo:
            native = todo.pop()
            if native in seen:
                continue
            seen.add(native)
            if native + "::" + spelling in SDK_FLAGS:
                return SDK_FLAGS[native + "::" + spelling]
            record = NATIVE_CLASSES.get(native)
            if record is not None:
                todo.extend(record["bases"])
        return None

    def conversion(self, spelling: str, owner: str, result: bool = False) -> Conversion | None:
        """Infer a supported native conversion, retaining its actual type dependencies."""
        bare = re.sub(r"\bconst\b|[&]", "", spelling).strip()
        if spelling.strip() in {"const char *", "const char*"} and not result:
            return Conversion("QtArgument<QString>", f"string | {self.string_type}",
                              "{expr}.value.toUtf8().constData()", "{expr}")
        if result and bare == "QString" and self.config.get("_ustring_results"):
            return Conversion("QString", self.string_type, "{expr}",
                              "luabridge::LuaRef(L, QtValueRef<QString>({expr}))")
        if "&" in spelling and not spelling.startswith("const "):
            backend = BACKENDS.get(bare, {}).get("cpp_type", bare)
            if (
                not result
                and spelling.endswith("&")
                and not spelling.endswith("&&")
                and backend != bare
            ):
                policy = self.policies.get(bare)
                access = "{expr}.value" if policy is not None and policy["kind"] == "variant" else "{expr}.native()"
                return Conversion(
                    backend + " &", self.common_type_name(bare), access, "qtToLua(L, {expr})"
                )
            if (
                not result
                and spelling.endswith("&")
                and not spelling.endswith("&&")
                and bare in NATIVE_CLASSES
                and self.allowed(bare)
                and not self.object_type(bare)
            ):
                return Conversion(
                    bare + " &",
                    "_qt_" + bare,
                    "{expr}",
                    "qtToLua(L, {expr})",
                    () if bare in self.existing else (bare,),
                )
            return None
        flags = self.flags_type(bare, owner)
        if flags:
            return Conversion(
                f"QtArgument<{flags}>", "number", "{expr}.value", "qtToLua(L, {expr})"
            )
        enum = self.enum_type(bare, owner)
        if enum:
            domain = sorted(set(SDK_ENUMS[enum].values())) if not result else []
            cpp = f"QtArgument<{enum}" + (", " + ", ".join(str(value) for value in domain) if domain else "") + ">"
            return Conversion(cpp, "number", "{expr}.value", "static_cast<int>({expr})")
        views = {
            "QStringView": "QString",
            "QAnyStringView": "QString",
            "QByteArrayView": "QByteArray",
        }
        if bare in views:
            native = views[bare]
            return Conversion(
                f"QtArgument<{native}>",
                "string",
                bare + "({expr}.value)",
                "qtToLua(L, {expr}.to" + ("String" if native == "QString" else "ByteArray") + "())",
            )
        base = mapped_type(spelling)
        returned = mapped_type(spelling, True)
        if base is not None or returned is not None:
            chosen = returned if result else base
            if chosen is None:
                return None
            annotation = object_field(object_field(object_field(self.config, "sdk_bindings"),
                                                   "type_annotations"), bare)
            lua_type = text(annotation, "result" if result else "argument", chosen[1])
            return Conversion(
                chosen[0],
                f"string | {self.string_type}" if bare == "QString" and not result else lua_type,
                base[2] if base else "{expr}",
                returned[2] if returned else "{expr}",
            )
        pointer = re.fullmatch(r"(Q\w+)\s*\*", bare)
        if pointer:
            native = pointer[1]
            if (
                not self.allowed(native)
                or not self.object_type(native)
            ):
                return None
            if native in self.existing or native in {"QObject", "QWidget", "QLayout"}:
                return Conversion(
                    f"QtArgument<{native} *>",
                    "_qt_" + native + "?",
                    "{expr}.value",
                    "qtToLua(L, {expr})",
                    (native,),
                )
            immutable = spelling.startswith("const ")
            read = f"qobject_cast<{native} *>({{expr}}.get())"
            if not immutable:
                read = "({expr}.requireWritable(), " + read + ")"
            write = (f"luabridge::LuaRef(L, QtObjectRef<{native}>(const_cast<{native} *>({{expr}}), false, true))"
                     if immutable else f"luabridge::LuaRef(L, QtObjectRef<{native}>({{expr}}, false))")
            write = "({expr} ? " + write + " : luabridge::LuaRef(L))"
            return Conversion("QObjectRef", "_qt_" + native + ("?" if result else ""), read, write, (native,))
        alias = SDK_CONTAINER_ALIASES.get(bare) or SDK_CONTAINER_ALIASES.get(owner + "::" + bare)
        if alias and alias != bare:
            return self.conversion(alias, owner, result)
        container = re.fullmatch(r"(QList|QVector)<(.+)>", bare)
        if container:
            element = self.conversion(container[2].strip(), owner, result)
            if element:
                return Conversion(
                    f"QtArgument<{bare}>",
                    "{" + element.lua + "}",
                    "{expr}.value",
                    "qtToLua(L, {expr})",
                    element.dependencies,
                )
        if bare in NATIVE_CLASSES and self.allowed(bare) and not self.object_type(bare):
            record = NATIVE_CLASSES[bare]
            if not record.get("copyable", True) or record["abstract"]:
                return None
            dependencies = (bare,)
            return Conversion(
                f"QtArgument<{bare}>",
                "_qt_" + bare,
                "{expr}.value",
                "qtToLua(L, {expr})",
                dependencies,
            )
        return None

    def output_type(self, spelling: str, owner: str) -> tuple[str, Conversion, bool] | None:
        """Recognize mutable scalar/value result parameters, excluding QObject pointers."""
        if spelling.startswith("const ") or not spelling.rstrip().endswith(("*", "&")):
            return None
        bare = spelling.rstrip().rstrip("*& ").strip()
        if bare in NATIVE_CLASSES:
            if self.object_type(bare) or spelling.rstrip().endswith("&"):
                return None
        converted = self.conversion(bare, owner, True)
        if converted is None or bare == "void":
            return None
        native = self.enum_type(bare, owner) or bare
        return native, converted, spelling.rstrip().endswith("*")

    def dependencies(self, native: str, static_only: bool = False) -> set[str]:
        """Find dependencies only through representable public signatures."""
        record = NATIVE_CLASSES[native]
        result: set[str] = set()
        for method in self.methods(native):
            if not self.method_allowed(native, method) or (static_only and not method["static"]):
                continue
            refinement = text(object_field(self.adapter(native), "return_types"), method["name"])
            if refinement:
                converted = self.conversion(refinement, native, True)
                if converted:
                    result.update(converted.dependencies)
            for spelling in [method["result"], *method["args"]]:
                converted = self.conversion(spelling, native, bool(method.get("signal")) or spelling == method["result"])
                output = None if method.get("signal") else self.output_type(spelling, native)
                if converted:
                    result.update(converted.dependencies)
                if output:
                    result.update(output[1].dependencies)
        for field in record.get("fields", []):
            converted = self.conversion(text(field, "type"), native, True)
            if converted:
                result.update(converted.dependencies)
        for args in [] if static_only else record.get("constructors", []):
            for spelling in args:
                converted = self.conversion(spelling, native)
                if converted:
                    result.update(converted.dependencies)
        return result

    def method_allowed(self, native: str, method: NativeMethod) -> bool:
        """Apply API baseline, deprecation and member policy before emitting code."""
        return (
            not method["deprecated"]
            and not method["variadic"]
            and method["name"].isidentifier()
            and not method["name"].startswith("operator")
            and not excluded_method(self.members, native, method["name"], method["args"])
        )

    def default(self, value: str, spelling: str, owner: str) -> str:
        """Qualify native enum defaults after moving calls outside their class scope."""
        value = re.sub(
            r"\b([A-Za-z_]\w*)\s*::",
            lambda match: (self.enum_type(match[1], owner) or match[1]) + "::",
            value,
        )
        enum = self.enum_type(re.sub(r"\bconst\b|[&*]", "", spelling).strip(), owner)
        if enum and value in SDK_ENUMS[enum]:
            return enum.rsplit("::", 1)[0] + "::" + value
        if value.isidentifier():
            todo = [owner]
            seen: set[str] = set()
            while todo:
                native = todo.pop()
                if native in seen:
                    continue
                seen.add(native)
                if value in SDK_ENUMS.get(native + "::", {}):
                    return native + "::" + value
                record = NATIVE_CLASSES.get(native)
                if record is not None:
                    if any(
                        field.get("static") and field.get("name") == value
                        for field in record.get("fields", [])
                    ):
                        return native + "::" + value
                    todo.extend(record["bases"])
        return value

    def method(
        self, native: str, method: NativeMethod, provider: str = "", parent_index: int | None = None
    ) -> list[tuple[str, str, str]]:
        """Emit callable overload prefixes, including actual C++ output parameters."""
        refined = text(object_field(self.adapter(native), "return_types"), method["name"])
        if refined:
            original = method["result"].replace("*", "").strip()
            desired = refined.replace("*", "").strip()
            pending = [desired]
            seen: set[str] = set()
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                pending.extend(NATIVE_CLASSES.get(current, {}).get("bases", []))
            if "*" not in method["result"] or original not in seen or not self.object_type(desired):
                raise ValueError("Return refinement requires a QObject-derived native pointer")
        result = self.conversion(refined or method["result"], native, True)
        if result is None:
            self.rejected.append(
                {
                    "class": native,
                    "method": method["name"],
                    "reason": "unsupported result",
                    "type": method["result"],
                }
            )
            return []
        bound = {parent_index: "nullptr"} if parent_index is not None else {}
        inputs: list[tuple[int, Conversion]] = []
        outputs: list[tuple[int, str, Conversion, bool]] = []
        for index, spelling in enumerate(method["args"]):
            if index in bound:
                continue
            output = self.output_type(spelling, native)
            if output:
                outputs.append((index, *output))
            else:
                converted = self.conversion(spelling, native)
                if converted is None:
                    # A trailing unsupported argument can still be omitted using its native default.
                    defaults = method.get("defaults", [])
                    if index < len(defaults) and all(
                        value is not None for value in defaults[index:]
                    ):
                        break
                    self.rejected.append(
                        {
                            "class": native,
                            "method": method["name"],
                            "reason": "unsupported argument",
                            "type": spelling,
                        }
                    )
                    return []
                inputs.append((index, converted))
        defaults = method.get("defaults", [None] * len(method["args"]))
        required = sum(defaults[index] is None for index, _ in inputs)
        receiver_type = f"QtObjectRef<{native}>" if self.object_type(native) else native
        receiver = "" if method["static"] or provider else receiver_type + " &self"
        target = (
            native + "::"
            if method["static"]
            else ("self.get()->" if self.object_type(native) else "self.")
        )
        if provider and not method["static"]:
            target = f"QtObjectRef<{native}>({provider}(), false).get()->"
        overloads: list[tuple[str, str, str]] = []
        for count in range(required, len(inputs) + 1):
            chosen = inputs[:count]
            arguments = [converted.cpp + f" arg{i}" for i, (_, converted) in enumerate(chosen)]
            call_args = dict(bound)
            call_args.update(
                {
                    index: converted.read.format(expr=f"arg{i}")
                    for i, (index, converted) in enumerate(chosen)
                }
            )
            # Let C++ supply trailing defaults; materialize only defaults before outputs.
            call_limit = max([*call_args, *(index for index, *_ in outputs)], default=-1) + 1
            for index, _ in inputs[count:]:
                if index >= call_limit:
                    continue
                value = defaults[index]
                if value is None:
                    raise ValueError("Missing native default for optional overload")
                call_args[index] = self.default(value, method["args"][index], native)
            body: list[str] = []
            if receiver and self.object_type(native) and not method["const"]:
                body.append("self.requireWritable();")
            returns: list[tuple[str, Conversion]] = []
            for index, kind, converted, pointer in outputs:
                body.append(f"{kind} output{index}{{}};")
                call_args[index] = ("&" if pointer else "") + f"output{index}"
            if any(index not in call_args for index in range(call_limit)):
                continue
            call = (
                target
                + method["name"]
                + "("
                + ", ".join(call_args[index] for index in range(call_limit))
                + ")"
            )
            adapter = self.adapter(native)
            receiver_pointer = ("self.get()" if self.object_type(native) else "&self") if receiver else f"static_cast<{native} *>(nullptr)"
            guard = text(adapter, "guard")
            if guard:
                selector_name = text(adapter, "guard_selector")
                guard_args = [receiver_pointer]
                if selector_name:
                    selector = object_field(object_field(object_field(self.config, "sdk_bindings"),
                                                         "guard_selectors"), selector_name)
                    value = text(selector, "const" if method["const"] else "mutable")
                    for rule in object_list_field(selector, "rules"):
                        if any(fnmatch.fnmatchcase(method["name"], pattern)
                               for pattern in string_list_field(rule, "methods")):
                            value = text(rule, "value")
                            break
                    if not value:
                        raise ValueError("Guard selector has no matching rule or default: " + selector_name)
                    guard_args.insert(0, value)
                body.append(f'{guard}(' + ", ".join(guard_args) + ");")
            redirected = text(object_field(adapter, "methods"), method["name"])
            if redirected:
                if method["static"]:
                    raise ValueError("Call adapters require an instance method")
                call = redirected + "(" + ", ".join([receiver_pointer, *[call_args[index] for index in range(call_limit)]]) + ")"
            if refined:
                call = "qobject_cast<" + refined + ">(" + call + ")"
            if method["result"] == "void":
                body.append(call + ";")
            else:
                body.append("auto result = " + call + ";")
                returns.append(("result", result))
            ownership = object_field(
                object_field(self.config, "sdk_bindings"), "transfer_ownership"
            )
            adopted = ownership.get(native + "::" + method["name"], [])
            if not isinstance(adopted, list) or any(
                not isinstance(index, int) for index in cast(list[object], adopted)
            ):
                raise ValueError("Ownership policy must list native argument indexes")
            for position, (index, converted) in enumerate(chosen):
                if index in adopted:
                    if converted.cpp != "QObjectRef":
                        raise ValueError("Ownership transfer requires a QObject argument")
                    body.append(f"arg{position}.releaseOwnership();")
            returns.extend((f"output{index}", converted) for index, _, converted, _ in outputs)
            expressions = [converted.write.format(expr=value) for value, converted in returns]
            if len(expressions) == 1:
                body.append("return " + expressions[0] + ";")
            elif expressions:
                body.append("return std::make_tuple(" + ", ".join(expressions) + ");")
            parameters = ", ".join(part for part in [receiver, *arguments, "lua_State *L"] if part)
            signature = ", ".join(
                (["self: _qt_" + native] if receiver else [])
                + [f"arg{i}: {converted.lua}" for i, (_, converted) in enumerate(chosen)]
            )
            results = [converted.lua for _, converted in returns]
            lua_result = "(" + ", ".join(results) + ")" if len(results) != 1 else results[0]
            checker = ",".join(converted.cpp for _, converted in chosen)
            overloads.append(
                (
                    checker,
                    f"[]({parameters}) {{ " + " ".join(body) + " }",
                    "((" + signature + ") -> " + lua_result + ")",
                )
            )
        return overloads

    def emit_class(
        self,
        native: str,
        output: pathlib.Path,
        static_only: bool,
        provider: str = "",
        implicit_parent: bool = False,
    ) -> tuple[str, str, str]:
        """Write one native class binding and return its symbol, type and class-table shape."""
        record = NATIVE_CLASSES[native]
        wrapper = f"QtObjectRef<{native}>" if self.object_type(native) else native
        symbol = "register_sdk_" + identifier(native)
        includes = {native}
        if provider:
            owner, factory = provider.rsplit("::", 1)
            record_provider = NATIVE_CLASSES.get(owner)
            if record_provider is None or not any(
                method["name"] == factory
                and method["static"]
                and method.get("minimum_args", len(method["args"])) == 0
                and method["result"].replace("*", "").strip() == native
                for method in record_provider["methods"]
            ):
                raise ValueError("Invalid native instance provider: " + provider)
            includes.add(owner)
        includes.update(self.dependencies(native, static_only))
        connector, signal_signatures = signal_connector(self, native) if self.object_type(native) and not static_only and not provider else ([], [])
        code = [
            '#include "qtluau/packages.hpp"',
            '#include "qtluau/object_ref.hpp"',
            '#include "qtluau/callback.hpp"',
            '#include <QMetaMethod>',
            *[f'#include "{header}"' for header in string_list_field(self.adapter(native), "includes")],
            *[f"#include <{name}>" for name in sorted(includes)],
            "#include <tuple>",
            "namespace qtluau {",
            *connector,
            f"void {symbol}(lua_State *L) {{",
            f'RegistrationGuard registration(L, "sdk.{native}"); if (!registration) {{ return; }}',
        ]
        register = (
            f"deriveClass<{wrapper}, QObjectRef>"
            if self.object_type(native)
            else f"beginClass<{native}>"
        )
        code.append(
            f'auto cls = luabridge::getGlobalNamespace(L).beginNamespace("{self.module}").{register}("{native}");'
        )
        constructors: list[str] = []
        constructor_types: list[str] = []
        constructor_arguments: list[list[str]] = []
        seen_ctors: set[str] = set()
        if not static_only and not provider and not record["abstract"] and self.adapter(native).get("constructible", True):
            # Enum values share Luau's numeric representation with integers.
            # Match a known enum domain first, then allow ordinary numeric overloads.
            constructor_sets = sorted(record.get("constructors", []),
                key=lambda args: -sum(self.enum_type(re.sub(r"\bconst\b|[&]", "", kind).strip(), native) is not None
                                      for kind in args))
            for args in constructor_sets:
                mapped: list[Conversion | None] = []
                for kind in args:
                    converted = self.conversion(kind, native)
                    enum = self.enum_type(re.sub(r"\bconst\b|[&]", "", kind).strip(), native)
                    if converted is not None and enum and not self.flags_type(kind, native):
                        domain = sorted(set(SDK_ENUMS[enum].values()))
                        if domain:
                            converted = replace(converted, cpp=f"QtArgument<{enum}, " + ", ".join(str(value) for value in domain) + ">")
                    mapped.append(converted)
                if any(converted is None for converted in mapped):
                    continue
                converted = [value for value in mapped if value is not None]
                checker = ",".join(value.cpp for value in converted)
                if checker in seen_ctors:
                    continue
                seen_ctors.add(checker)
                params = ", ".join(value.cpp + f" arg{i}" for i, value in enumerate(converted))
                values = ", ".join(
                    value.read.format(expr=f"arg{i}") for i, value in enumerate(converted)
                )
                factory = text(self.adapter(native), "factory")
                construction = f"{factory}({values})" if factory else f"new {native}({values})"
                tracked = self.object_type(native) and self.adapter(native).get("context_owned", False)
                if tracked:
                    construction = f"trackLuaObject(L, {construction})"
                expression = (
                    f"{wrapper}({construction}, true)"
                    if self.object_type(native)
                    else native + "(" + values + ")"
                )
                constructors.append(
                    "[](void *memory"
                    + (", " if params else "")
                    + params
                    + (", lua_State *L" if tracked else "")
                    + ") { return new (memory) "
                    + expression
                    + "; }"
                )
                constructor_types.append(
                    "((self: any"
                    + (", " if converted else "")
                    + ", ".join(f"arg{i}: {value.lua}" for i, value in enumerate(converted))
                    + ") -> _qt_"
                    + native
                    + ")"
                )
                constructor_arguments.append([value.lua for value in converted])
        if constructors:
            code.append("cls.addConstructor(" + ", ".join(constructors) + ");")
        methods: dict[tuple[str, bool], dict[str, tuple[str, str]]] = {}
        for method in sorted(self.methods(native),
                key=lambda method: -sum(self.enum_type(re.sub(r"\bconst\b|[&]", "", kind).strip(), native) is not None
                                        for kind in method["args"])):
            if method.get("signal") or not self.method_allowed(native, method) or (static_only and not method["static"]):
                continue
            overloads = self.method(native, method, provider)
            if implicit_parent and method["static"]:
                for index, (name, spelling) in enumerate(
                    zip(method.get("parameter_names", []), method["args"])
                ):
                    if name == "parent" and re.sub(r"\s+", "", spelling) == "QWidget*":
                        overloads.extend(self.method(native, method, provider, index))
                        break
            for checker, expression, signature in overloads:
                methods.setdefault(
                    (method["name"], method["static"] or bool(provider)), {}
                ).setdefault(checker, (expression, signature))
        instance: list[str] = []
        if signal_signatures:
            instance.append("    connect: " + " & ".join("(" + signature + ")" for signature in signal_signatures)
                            + f" & ((self: _qt_{native}, signal: string, callback: (...any) -> ()) -> ()),")
            code.append(f"registerSignalConnector(L, &{native}::staticMetaObject, &connect_sdk_{native});")
        fields: list[str] = []
        for (name, static), overloads in methods.items():
            code.append(
                f'cls.add{"Static" if static else ""}Function("{name}", '
                + ", ".join(value[0] for value in overloads.values())
                + ");"
            )
            (fields if static else instance).append(
                f"    {name}: "
                + " & ".join(dict.fromkeys(value[1] for value in overloads.values()))
                + ","
            )
        for field in record.get("fields", []):
            kind, name = text(field, "type"), text(field, "name")
            converted = self.conversion(kind, native, True)
            if field.get("static") or converted is None or static_only:
                continue
            expression = converted.write.format(expr="self." + name)
            # Qt's public result structures are values; QObject data members remain inaccessible here.
            if self.object_type(native):
                continue
            code.append(
                f'cls.addProperty("{name}", [](const {native} &self, lua_State *L) {{ return {expression}; }});'
            )
            instance.append(f"    {name}: {converted.lua},")
        if any(not static and (name, True) in methods for name, static in methods):
            code.append("preferStaticClassFunctions(L, cls);")
        code.extend(["guardClassMethods(L, cls); cls.endClass();", "}", "}"])
        enum_owners = {native}
        pending_bases = list(record["bases"]) if self.adapter(native).get("inherited_methods") else []
        while pending_bases:
            base = pending_bases.pop()
            if base in enum_owners:
                continue
            enum_owners.add(base)
            base_record = NATIVE_CLASSES.get(base)
            if base_record is not None:
                pending_bases.extend(base_record["bases"])
        enums = [
            (name, values)
            for name, values in SDK_ENUMS.items()
            if name.rsplit("::", 1)[0] in enum_owners
        ]
        enum_code: list[str] = []
        for enum, values in enums:
            label = enum.rsplit("::", 1)[1]
            if not label.isidentifier():
                continue
            enum_code.extend(
                [
                    f"auto enum_{label} = luabridge::newTable(lua_mainthread(L));",
                    *[f'enum_{label}["{key}"] = {value};' for key, value in values.items()],
                    f'enum_{label}.push(L); lua_setreadonly(L, -1, true); lua_pop(L, 1);',
                    f'cls.addStaticProperty("{label}", [enum_{label}]() {{ return enum_{label}; }});',
                ]
            )
            fields.append(f"    {label}: {{" + ", ".join(f"{key}: number" for key in values) + "},")
        if enum_code:
            code[-3:-3] = enum_code
        if constructor_types:
            # A trailing nullable parameter is already optional in Luau. Keep
            # its longer signature, rather than an ambiguous shorter duplicate.
            signatures = [signature for signature, args in zip(constructor_types, constructor_arguments)
                          if not any(len(other) > len(args) and other[:len(args)] == args
                                     and all(kind.endswith("?") for kind in other[len(args):])
                                     for other in constructor_arguments)]
            fields.append("    __call: " + " & ".join(dict.fromkeys(signatures)) + ",")
        code.insert(-2, "registration.complete();")
        write(output / f"sdk_{native}.cpp", "\n".join(code) + "\n")
        return (
            symbol,
            "type _qt_" + native + " = {\n" + "\n".join(instance) + "\n}\n",
            "{\n" + "\n".join(fields) + "\n}",
        )


def emit_framework_bindings(
    config: JsonObject, output: pathlib.Path
) -> tuple[list[JsonObject], dict[str, str]]:
    """Generate Qt-native module exports without a second handwritten interface contract."""
    qt_module = qt_namespace(config)
    selected = string_list_field(config, "framework_bindings")
    configured_modules = object_field(object_field(config, "sdk_bindings"), "modules")
    if not selected and not configured_modules:
        for key in ("_sdk_types", "_sdk_public_types", "_sdk_module_types"):
            config.pop(key, None)
        for stale in (output / "custom").glob("sdk_*.cpp"):
            stale.unlink()
        return [], {}
    policy: JsonObject = json.loads((support_root() / "config/framework-bindings.json").read_text())
    groups = object_field(policy, "groups")
    if len(set(selected)) != len(selected) or set(selected) - set(groups):
        raise ValueError("Unknown or duplicate SDK binding group")
    generator = SdkBindings(config)
    roots: dict[str, JsonObject] = {}
    providers: dict[str, tuple[str, NativeMethod]] = {}
    module_tables: dict[str, dict[str, str]] = {}
    functions: dict[str, JsonObject] = {}
    aliases: dict[str, str] = {}
    for module in configured_modules:
        table = object_field(configured_modules, module)
        module_tables[module] = {name: text(table, name) for name in table}
        for native in module_tables[module].values():
            roots.setdefault(native, {})
    for group in selected:
        entry = object_field(groups, group)
        for module in object_field(entry, "functions"):
            functions[module] = object_field(object_field(entry, "functions"), module)
        for native in object_field(entry, "classes"):
            roots[native] = object_field(object_field(entry, "classes"), native)
        for alias, native in object_field(entry, "aliases").items():
            if not isinstance(native, str):
                raise ValueError("Aliases must select native classes")
            aliases[alias] = native
            roots.setdefault(native, {})
        for module in object_field(entry, "modules"):
            table = object_field(object_field(entry, "modules"), module)
            module_tables[module] = {name: text(table, name) for name in table}
            for native in module_tables[module].values():
                roots.setdefault(native, {})
        for module, expression in object_field(entry, "providers").items():
            if not isinstance(expression, str) or "::" not in expression:
                raise ValueError("Providers must select a native static method")
            owner, name = expression.rsplit("::", 1)
            record = NATIVE_CLASSES.get(owner)
            methods = (
                []
                if record is None
                else [
                    method
                    for method in record["methods"]
                    if method["static"]
                    and method["name"] == name
                    and method.get("minimum_args", len(method["args"])) == 0
                ]
            )
            if len(methods) != 1:
                raise ValueError(
                    f"Provider is not an unambiguous zero-argument factory: {expression}"
                )
            providers[module] = owner, methods[0]
            native = methods[0]["result"].replace("*", "").strip()
            roots.setdefault(native, {})
    for native in string_list_field(config, "_sdk_required_types"):
        roots.setdefault(native, {})
    todo = list(roots)
    while todo:
        native = todo.pop()
        if native in generator.classes or native in generator.existing:
            continue
        if not generator.allowed(native):
            if native in roots:
                raise ValueError("Excluded or undiscovered SDK root: " + native)
            continue
        generator.classes.add(native)
        todo.extend(
            generator.dependencies(native, bool(roots.get(native, {}).get("static_only", False)))
            - generator.classes
        )
    for module in object_field(object_field(config, "sdk_bindings"), "module_dependencies"):
        rule = object_field(object_field(object_field(config, "sdk_bindings"), "module_dependencies"), module)
        selected_modules = string_list_field(rule, "sdk_modules")
        if text(rule, "alias_style", "snake_case") != "snake_case":
            raise ValueError("SDK dependency aliases require snake_case")
        table = module_tables.setdefault(module, {})
        for native in sorted(generator.classes):
            source = NATIVE_CLASSES[native]["source"].replace("\\", "/")
            if not any("/" + name + "/" in source or "/" + name + ".framework/" in source
                       for name in selected_modules):
                continue
            if native in table.values():
                continue
            alias = snake_case(native.removeprefix("Q"))
            if alias in table and table[alias] != native:
                raise ValueError("SDK module alias collision: " + alias)
            table[alias] = native
    config["_sdk_types"] = sorted(generator.classes)
    target = output / "custom"
    target.mkdir(exist_ok=True)
    expected_sources = {f"sdk_{native}.cpp" for native in generator.classes} | {"sdk_modules.cpp"}
    for stale in target.glob("sdk_*.cpp"):
        if stale.name not in expected_sources:
            stale.unlink()
    symbols: list[str] = []
    types: list[str] = []
    shapes: dict[str, str] = {}
    for native in sorted(generator.classes):
        symbol, definition, shape = generator.emit_class(
            native,
            target,
            bool(roots.get(native, {}).get("static_only", False)),
            str(roots.get(native, {}).get("provider", "")),
            bool(roots.get(native, {}).get("implicit_parent", False)),
        )
        symbols.append(symbol)
        types.append(definition)
        shapes[native] = shape
    declarations = [f"void {symbol}(lua_State *L);" for symbol in symbols]
    public_roots = set(aliases.values()) | set(string_list_field(config, "_sdk_required_types"))
    for module, table in module_tables.items():
        if not requires_module(config, module):
            public_roots.update(table.values())
    public_classes: set[str] = set()
    pending = list(public_roots)
    while pending:
        native = pending.pop()
        if native in public_classes or native not in generator.classes:
            continue
        public_classes.add(native)
        pending.extend(generator.dependencies(native, bool(roots.get(native, {}).get("static_only", False))))
    config["_sdk_public_types"] = sorted(public_classes)
    module_types: dict[str, list[str]] = {"": sorted(public_classes), qt_module: sorted(generator.classes)}
    config["_sdk_module_types"] = module_types
    source = [
        '#include "qtluau/packages.hpp"', '#include "qtluau/object_ref.hpp"',
        *[f"#include <{name}>" for name in sorted(generator.classes | {owner for owner, _ in providers.values()})],
        "namespace qtluau {", *declarations,
        "void registerFrameworkQtSdk(lua_State *L) {",
        *[f"register_sdk_{native}(L);" for native in sorted(generator.classes - public_classes)],
        "}", "void registerFrameworkSdk(lua_State *L) {",
        *[f"register_sdk_{native}(L);" for native in sorted(public_classes)],
    ]
    public: dict[str, list[str]] = {}
    for alias, native in aliases.items():
        parts = alias.split(".")
        for part in parts:
            identifier(part)
        if native not in shapes:
            raise ValueError("SDK alias has no generated type: " + native)
        source.extend(
            [f'lua_getglobal(L, "{qt_module}");', f'lua_getfield(L, -1, "{native}"); lua_remove(L, -2);']
        )
        if len(parts) == 1:
            source.append(f'lua_setglobal(L, "{alias}");')
            public[alias] = [f"declare {alias}: {shapes[native]}\n"]
        elif len(parts) == 2:
            source.extend(
                [
                    f'lua_getglobal(L, "{parts[0]}");',
                    "if (!lua_istable(L, -1)) { lua_pop(L, 1); lua_newtable(L); lua_pushvalue(L, -1);"
                    + f'lua_setglobal(L, "{parts[0]}");'
                    + "}",
                    "lua_insert(L, -2);",
                    f'lua_setfield(L, -2, "{parts[1]}"); lua_pop(L, 1);',
                ]
            )
            public.setdefault(parts[0], []).append(f"    {parts[1]}: {shapes[native]},")
        else:
            raise ValueError("SDK aliases support one namespace level")
    source.append("}")
    metadata: list[JsonObject] = []
    definitions: dict[str, str] = {"": "\n".join(types)}
    for name, values in public.items():
        definitions[""] += (
            values[0]
            if values[0].startswith("declare ")
            else f"declare {name}: {{\n" + "\n".join(values) + "\n}\n"
        )
    namespace_shapes: dict[str, str] = {}
    namespace_rules = object_field(object_field(config, "sdk_bindings"), "enum_namespaces")
    for owner in namespace_rules:
        identifier(owner)
        fields: list[str] = []
        source.insert(source.index("namespace qtluau {") + 1, f"void registerEnums_{owner}(lua_State *L);")
        source.append(f'void registerEnums_{owner}(lua_State *L) {{')
        source.append(f'RegistrationGuard guard(L, "enum.{owner}"); if (!guard) {{ return; }}')
        source.append('lua_newtable(L);')
        for enum, values in sorted(SDK_ENUMS.items()):
            if enum.rsplit("::", 1)[0] != owner:
                continue
            label = identifier(enum.rsplit("::", 1)[1])
            source.append('lua_newtable(L);')
            for key, value in values.items():
                source.append(f'lua_pushnumber(L, {value}); lua_rawsetfield(L, -2, "{key}");')
            source.append(f'lua_setreadonly(L, -1, true); lua_rawsetfield(L, -2, "{label}");')
            fields.append(f"    {label}: {{" + ", ".join(f"{key}: number" for key in values) + "},")
        if not fields:
            raise ValueError("Undiscovered enum namespace: " + owner)
        source.extend(['lua_setreadonly(L, -1, true);', f'lua_getglobal(L, "{qt_module}"); lua_insert(L, -2);', f'lua_rawsetfield(L, -2, "{owner}"); lua_pop(L, 1); guard.complete();', '}'])
        namespace_shapes[owner] = "{\n" + "\n".join(fields) + "\n}"
        declarations.append(f"void registerEnums_{owner}(lua_State *L);")
    # Namespace values share registration with the Qt SDK loader.
    position = source.index("void registerFrameworkQtSdk(lua_State *L) {") + 1
    source[position:position] = [f"registerEnums_{owner}(L);" for owner in namespace_shapes]
    qt_fields = [f"    {native}: {shape}," for native, shape in shapes.items()]
    qt_fields.extend(f"    {owner}: {shape}," for owner, shape in namespace_shapes.items())
    definitions[qt_module] = f"declare {qt_module}: {{\n" + "\n".join(qt_fields) + "\n}\n"

    def make_entry(symbol: str, module: str) -> JsonObject:
        """Describe a generated registration to the existing module exporter."""
        return {
            "binding": "custom",
            "module": module,
            "namespace": module,
            "name": symbol,
            "register": symbol,
            "base": "",
            "methods": [],
            "properties": [],
        }

    metadata.append(make_entry("registerFrameworkSdk", ""))
    metadata.append(make_entry("registerFrameworkQtSdk", qt_module))
    for module, rule in functions.items():
        emitter = SdkBindings(dict(config, _ustring_results=rule.get("qstring_result") == "ustring"))
        symbol = "registerSdkModule_" + identifier(module)
        metadata.append(make_entry(symbol, module))
        source[0:0] = [f"#include <{header}>" for header in string_list_field(rule, "headers")]
        source.extend([f"void {symbol}(lua_State *L) {{",
                       f'auto scope = luabridge::getGlobalNamespace(L).beginNamespace("{module}");'])
        function_overloads: dict[str, dict[str, tuple[str, str]]] = {}
        for method in SDK_FUNCTIONS:
            if not emitter.method_allowed("", method) or not any(
                fnmatch.fnmatchcase(method["name"], pattern)
                for pattern in string_list_field(rule, "include")
            ):
                continue
            name = text(object_field(rule, "rename"), method["name"], method["name"])
            for checker, expression, signature in emitter.method("", method):
                function_overloads.setdefault(name, {}).setdefault(checker, (expression, signature))
        fields: list[str] = []
        for name, overloads in function_overloads.items():
            source.append(f'scope.addFunction("{name}", ' + ", ".join(v[0] for v in overloads.values()) + ");")
            fields.append(f"    {name}: " + " & ".join(dict.fromkeys(v[1] for v in overloads.values())) + ",")
        source.extend(["scope.endNamespace();", f'lua_getglobal(L, "{module}");',
                       f'rememberModule(L, "{module}", -1);', "lua_pop(L, 1);", "}"])
        definitions[module] = f"declare {module}: {{\n" + "\n".join(fields) + "\n}\n"
    for owner in namespace_rules:
        rule = object_field(namespace_rules, owner)
        module = text(rule, "module")
        alias = identifier(text(rule, "alias"))
        table = module_tables.setdefault(module, {})
        if alias in table and table[alias] != owner:
            raise ValueError("SDK enum alias collision: " + alias)
        table[alias] = owner
        shapes[owner] = namespace_shapes[owner]
    for module, table in module_tables.items():
        identifier(module)
        symbol = "registerSdkModule_" + module
        metadata.append(make_entry(symbol, module))
        source.append(f"void {symbol}(lua_State *L) {{")
        closure: set[str] = set()
        pending = list(table.values())
        while pending:
            native = pending.pop()
            if native in closure or native not in generator.classes:
                continue
            closure.add(native)
            pending.extend(generator.dependencies(native))
        module_types[module] = sorted(closure)
        source.extend(f"register_sdk_{native}(L);" for native in sorted(closure - public_classes))
        source.extend(f"registerEnums_{owner}(L);" for owner in namespace_rules
                      if text(object_field(namespace_rules, owner), "module") == module)
        fields: list[str] = []
        if set(table) == {""}:
            native = table[""]
            source.extend(
                [f'lua_getglobal(L, "{qt_module}");', f'lua_getfield(L, -1, "{native}"); lua_remove(L, -2);']
            )
            shape = shapes[native]
        else:
            source.append("lua_newtable(L);")
            for name, native in table.items():
                identifier(name)
                source.extend(
                    [
                        f'lua_getglobal(L, "{qt_module}");',
                        f'lua_getfield(L, -1, "{native}"); lua_remove(L, -2);',
                        f'lua_setfield(L, -2, "{name}");',
                    ]
                )
                fields.append(f"    {name}: {shapes[native]},")
            shape = "{\n" + "\n".join(fields) + "\n}"
        source.append(f'rememberModule(L, "{module}", -1);')
        if not requires_module(config, module):
            source.append(f'lua_pushvalue(L, -1); lua_setglobal(L, "{module}");')
        source.extend(["lua_pop(L, 1);", "}"])
        definitions[module] = f"declare {module}: {shape}\n"
    for module, (owner, method) in providers.items():
        identifier(module)
        native = method["result"].replace("*", "").strip()
        symbol = "registerSdkModule_" + module
        metadata.append(make_entry(symbol, module))
        source.extend(
            [
                f"void {symbol}(lua_State *L) {{",
                f"auto *value = {owner}::{method['name']}();",
                'if (!value) { throw std::runtime_error("Qt provider is unavailable"); }',
                f'luabridge::LuaRef(L, QtObjectRef<{native}>(value, false)).push(); rememberModule(L, "{module}", -1); lua_pop(L, 1);',
                "}",
            ]
        )
        definitions[module] = f"declare {module}: _qt_{native}\n"
    source.append("}")
    write(target / "sdk_modules.cpp", "\n".join(source) + "\n")
    write(
        target / "sdk_discovery.json",
        json.dumps(
            {"classes": sorted(generator.classes), "unsupported": generator.rejected}, indent=2
        )
        + "\n",
    )
    return metadata, definitions
