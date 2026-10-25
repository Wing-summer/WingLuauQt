# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Shared typed models. Dynamic JSON is confined to configuration/AST boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, NotRequired, TypedDict, cast

JsonObject = dict[str, Any]
Parameter = tuple[str, str]
Parameters = list[Parameter]
Method = tuple[str, Parameters, str]


class ClassDefinition(TypedDict):
    """Describe a Luau-facing class, its base and callable surface."""
    #: Optional exposed base type.
    base: str | None
    #: Selected method signatures or method names.
    methods: list[Method]
    #: Supported native constructor overloads.
    constructors: list[Parameters]


class CommonTypePolicy(TypedDict):
    """Describe one canonical Qt type alias and selected methods."""
    #: Public Luau constructor or class-table alias.
    alias: str
    #: Typed compiler or conversion category.
    kind: str
    #: Whether the public construction entry is enabled.
    enabled: bool
    #: Selected method signatures or method names.
    methods: list[str]


class NativeMethod(TypedDict):
    """Retain native signature and qualifier information for generation."""
    #: Minimum arity after trailing default arguments.
    minimum_args: NotRequired[int]
    #: Native default expressions, in parameter order.
    defaults: NotRequired[list[str | None]]
    #: Native declaring class.
    owner: str
    #: Declaration or source file name.
    name: str
    #: Native return type spelling.
    result: str
    #: Native parameter type spellings.
    args: list[str]
    #: Native parameter names, in declaration order.
    parameter_names: NotRequired[list[str]]
    #: Whether the native method is const-qualified.
    const: bool
    #: Whether the native member is static.
    static: bool
    #: Whether the native function accepts variadic arguments.
    variadic: bool
    #: Whether the native declaration is deprecated.
    deprecated: bool


class NativeClass(TypedDict):
    """Describe a discovered Qt class and its binding dependencies."""
    #: Public constructor argument prefixes, including default-argument arities.
    constructors: NotRequired[list[list[str]]]
    #: Whether the native class permits copying.
    copyable: NotRequired[bool]
    #: Public data fields discovered from the native declaration.
    fields: NotRequired[list[JsonObject]]
    #: Direct native base class names.
    bases: list[str]
    #: Whether unresolved pure virtual members remain.
    abstract: bool
    #: Whether a public default constructor is available.
    default_ctor: bool
    #: Header path used by the scanner.
    source: str
    #: Native types required by selected signatures.
    dependencies: list[str]
    #: Selected method signatures or method names.
    methods: list[NativeMethod]


class DiscoveryReport(TypedDict, total=False):
    """Record selected classes and reasons for omitted native APIs."""
    #: Class names selected for binding.
    selected: list[str]
    #: Reasons for excluding discovered classes.
    rejected: dict[str, str]
    #: Native types required by selected signatures.
    dependencies: list[str]
    #: Signatures that lack supported conversions.
    unsupported_methods: list[JsonObject]


def object_field(parent: Mapping[str, object], key: str) -> JsonObject:
    """Validate a dynamic JSON/Clang object before traversing nested fields.

    Never use an untyped {} default in dictionary.get: it introduces an
    additional dictionary type rather than a record of the expected shape.
    Missing/null objects are empty; other non-object values are invalid input.
    """
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be an object")
    record = cast(dict[object, object], value)
    if not all(isinstance(name, str) for name in record):
        raise ValueError(f"{key} must have string keys")
    return cast(JsonObject, record)


def string_list_field(
    parent: Mapping[str, object], key: str, default: Sequence[str] = ()
) -> list[str]:
    """Read a configuration string array without propagating dynamic item types."""
    if key not in parent:
        return list(default)
    value = parent[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array of strings")
    result: list[str] = []
    for item in cast(list[object], value):
        if not isinstance(item, str):
            raise ValueError(f"{key} items must be strings")
        result.append(item)
    return result


def object_list_field(parent: Mapping[str, object], key: str) -> list[JsonObject]:
    """Read a JSON record array and validate each object's keys at the boundary."""
    if key not in parent:
        return []
    value = parent[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be an array of objects")
    result: list[JsonObject] = []
    for item in cast(list[object], value):
        candidate: Mapping[str, object] = {"item": item}
        if not isinstance(item, dict):
            raise ValueError(f"{key} items must be objects")
        result.append(object_field(candidate, "item"))
    return result
