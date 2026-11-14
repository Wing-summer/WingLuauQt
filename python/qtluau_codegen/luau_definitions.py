# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Render already-selected binding surfaces with tsujikiri's built-in Luau format."""

import json
from functools import cache
from io import StringIO

from tsujikiri.configurations import load_output_config
from tsujikiri.formats import resolve_format_path
from tsujikiri.generator import Generator
from tsujikiri.tir import TIRBase, TIRClass, TIRField, TIRMethod, TIRModule, TIRParameter

from .models import Method, Parameters
from .module_policy import KEYWORDS


@cache
def generator() -> Generator:
    """Reuse the built-in renderer without remapping already-resolved Luau types."""
    config = load_output_config(resolve_format_path("luau"))
    config.type_mappings.clear()
    return Generator(
        config,
        template_extends='{% extends "luau.tpl" %}{% block prologue %}{% endblock %}',
    )


def class_definition(
    name: str, methods: list[Method], base: str | None = None,
    fields: Parameters | None = None,
) -> str:
    """Render one nominal userdata type, preserving its overloads and fields.

    Args:
        name: Registered Luau type name.
        methods: Selected signatures with Luau parameter and result types.
        base: Optional registered base type.
        fields: Selected properties with their resolved Luau types.
    """
    record = TIRClass(name=name, qualified_name=name, namespace="")
    if base:
        record.bases.append(TIRBase(qualified_name=base))
    seen: set[tuple[str, tuple[tuple[str, str], ...], str]] = set()
    for method, parameters, result in methods:
        signature = (method, tuple(parameters), result)
        if signature in seen:
            continue
        seen.add(signature)
        record.methods.append(TIRMethod(
            name=method, spelling=method, qualified_name=f"{name}::{method}",
            return_type=result,
            parameters=[TIRParameter(name=key, type_spelling=kind) for key, kind in parameters],
        ))
    record.fields = [TIRField(name=f"[{json.dumps(key)}]" if key in KEYWORDS else key, type_spelling=kind) for key, kind in fields or []]
    output = StringIO()
    generator().generate(TIRModule(name="bindings", classes=[record]), output)
    return output.getvalue().strip()
