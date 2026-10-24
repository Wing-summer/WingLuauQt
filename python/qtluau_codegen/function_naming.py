# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Apply one naming policy to exported registration keys and Luau definitions."""

from __future__ import annotations

import pathlib
import re

from .models import JsonObject, object_field

FUNCTION_FIELD = re.compile(r"\b([A-Za-z_]\w*)(\s*:\s*)(?=\()")
FUNCTION_DECLARATION = re.compile(r"(\bfunction\s+)([A-Za-z_]\w*)(?=\()")
REGISTRATION = re.compile(
    r'(\.add(?:Static)?Function\s*\()\s*("[^"\n]+"|#[A-Za-z_]\w*|[A-Za-z_]\w*)(\s*,)'
)
PACKAGE_FUNCTION = re.compile(r'(packageFunction\s*\(\s*L\s*,\s*)("[^"\n]+")')


def snake_case(name: str) -> str:
    """Convert camel/Pascal case to snake_case, preserving metamethod prefixes."""
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def function_style(config: JsonObject) -> str:
    """Validate the naming boundary and return the configured public style."""
    style = object_field(config, "naming").get("functions", "snake_case")
    if not isinstance(style, str) or style not in {"native", "snake_case"}:
        raise ValueError("naming.functions must be native or snake_case")
    return style


def rename_declarations(config: JsonObject, source: str) -> str:
    """Apply the configured public function spelling to Luau declarations."""
    if function_style(config) == "native":
        return source
    source = FUNCTION_FIELD.sub(
        lambda match: (match[1] if match[1][0].isupper() else snake_case(match[1])) + match[2],
        source,
    )
    return FUNCTION_DECLARATION.sub(lambda match: match[1] + snake_case(match[2]), source)


def rename_registration_source(config: JsonObject, source: str) -> str:
    """Rename literal registration keys while preserving native C++ symbols."""
    if function_style(config) == "native":
        return source
    return REGISTRATION.sub(
        lambda match: (
            match[1]
            + ('"' + snake_case(match[2][1:-1]) + '"' if match[2].startswith('"') else match[2])
            + match[3]
        ),
        source,
    )


def rename_registrations(config: JsonObject, output: pathlib.Path) -> None:
    """Rename literal keys in additional generation-owned source files."""
    for path in output.glob("*.cpp"):
        source = path.read_text()
        rewritten = rename_registration_source(config, source)
        if rewritten != source:
            path.write_text(rewritten)


def apply_function_naming(config: JsonObject, output: pathlib.Path) -> None:
    """Transform exported method keys without changing native C++ symbols.

    Args:
        config: Policy with ``naming.functions`` set to native or snake_case.
        output: Generated project root; only generation-owned files are changed.

    Raises:
        ValueError: An unsupported naming style is requested.
    """
    style = function_style(config)
    if style == "native":
        (output / "include/qtluau/function_names.hpp").unlink(missing_ok=True)
        return
    names: set[str] = set()
    for path in (output / "definitions").glob("*.d.luau"):
        source = path.read_text()
        names.update(
            match[1] for match in FUNCTION_FIELD.finditer(source) if not match[1][0].isupper()
        )
        names.update(match[2] for match in FUNCTION_DECLARATION.finditer(source))
        source = FUNCTION_FIELD.sub(
            lambda m: (m[1] if m[1][0].isupper() else snake_case(m[1])) + m[2], source
        )
        source = FUNCTION_DECLARATION.sub(lambda m: m[1] + snake_case(m[2]), source)
        path.write_text(source)
    for path in output.rglob("*"):
        if path.suffix in {".cpp", ".inc"} and "native" not in path.relative_to(output).parts:
            source = path.read_text()
            names.update(
                match[2][1:-1]
                for match in REGISTRATION.finditer(source)
                if match[2].startswith('"')
            )
            names.update(match[2][1:-1] for match in PACKAGE_FUNCTION.finditer(source))
    mapping = {name: snake_case(name) for name in sorted(names) if name != snake_case(name)}
    header = [
        "#ifndef QTLUAU_GENERATED_FUNCTION_NAMES_HPP",
        "#define QTLUAU_GENERATED_FUNCTION_NAMES_HPP",
        "#include <string_view>",
        "namespace qtluau::generated {",
        "constexpr const char *functionName(const char *name) {",
    ]
    header.extend(
        f'if (std::string_view(name) == "{name}") {{ return "{value}"; }}'
        for name, value in mapping.items()
    )
    header.extend(["return name;", "}", "}", "#endif // QTLUAU_GENERATED_FUNCTION_NAMES_HPP", ""])
    (output / "include/qtluau/function_names.hpp").write_text("\n".join(header))
    bindings = output / "include/qtluau/bindings.hpp"
    bindings.write_text(
        re.sub(
            r"(#define [A-Z0-9_]+\n)",
            r'\1#include "qtluau/function_names.hpp"\n',
            bindings.read_text(),
            count=1,
        )
    )
    for path in output.rglob("*"):
        if path.suffix not in {".cpp", ".inc"} or "native" in path.relative_to(output).parts:
            continue
        source = path.read_text()
        source = REGISTRATION.sub(
            lambda m: m[1] + "qtluau::generated::functionName(" + m[2] + ")" + m[3], source
        )
        source = PACKAGE_FUNCTION.sub(
            lambda m: m[1] + "qtluau::generated::functionName(" + m[2] + ")", source
        )
        path.write_text(source)
