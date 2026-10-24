# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Copy configured application C++ adapters with their paired definitions."""

from __future__ import annotations

import pathlib
import shutil

from .assets import support_root
from .extensions import identifier
from .models import JsonObject, object_list_field, string_list_field


def extra_bindings(
    config: JsonObject, output: pathlib.Path, base: pathlib.Path
) -> tuple[list[JsonObject], dict[str, str]]:
    """Copy configured application sources and return module metadata and definitions."""
    metadata: list[JsonObject] = []
    definitions: dict[str, str] = {}
    target = output / "custom"
    target.mkdir(exist_ok=True)
    occupied: set[str] = set()
    for entry in object_list_field(config, "extra_bindings"):
        module = str(entry.get("module", ""))
        if module:
            identifier(module)
        symbol = identifier(entry["register"])
        for filename in string_list_field(entry, "files"):
            source = (
                support_root() / filename.removeprefix("@qtluau/")
                if filename.startswith("@qtluau/")
                else base / filename
            )
            if not source.is_file() or source.suffix not in {".cpp", ".hpp", ".h", ".inc"}:
                raise ValueError(f"Invalid extra binding source: {filename}")
            if source.name in occupied:
                raise ValueError(f"Duplicate extra binding filename: {source.name}")
            occupied.add(source.name)
            shutil.copy2(source, target / source.name)
        text: list[str] = []
        for filename in string_list_field(entry, "definitions"):
            source = (
                support_root() / filename.removeprefix("@qtluau/")
                if filename.startswith("@qtluau/")
                else base / filename
            )
            text.append(source.read_text())
        definitions[module] = definitions.get(module, "") + "\n".join(text)
        metadata.append(
            {
                "binding": "custom",
                "module": module,
                "namespace": module,
                "name": symbol,
                "register": symbol,
                "base": "",
                "methods": [],
                "properties": [],
            }
        )
    for stale in target.iterdir():
        if stale.is_file() and stale.name not in occupied:
            stale.unlink()
    return metadata, definitions
