# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Combine preprocessed Qt headers with QDoc introduction-version metadata."""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

from .models import JsonObject, object_field, string_list_field


def version_tuple(value: str) -> tuple[int, ...]:
    """Normalize a Qt version to a comparable three-component tuple."""
    match = re.search(r"\d+(?:\.\d+){0,2}", value)
    if not match:
        raise ValueError(f"Unrecognized Qt introduction version: {value}")
    parts = tuple(int(part) for part in match[0].split("."))
    return parts + (0,) * (3 - len(parts))


def index_files(config: JsonObject, actual: str) -> list[pathlib.Path]:
    """Discover matching QDoc indexes or reject an unverifiable older baseline."""
    qt = object_field(config, "qt")
    configured = string_list_field(qt, "api_indexes")
    files: list[pathlib.Path]
    if configured:
        files = [pathlib.Path(path) for path in configured]
    else:
        roots: set[pathlib.Path] = set()
        for tool in ("qtpaths6", "qtpaths", "qmake6", "qmake"):
            executable = shutil.which(tool)
            if executable:
                result = subprocess.run(
                    [executable, "--query" if "qtpaths" in tool else "-query", "QT_INSTALL_DOCS"],
                    capture_output=True, text=True, check=False,
                )
                if result.returncode == 0:
                    roots.add(pathlib.Path(result.stdout.strip()))
        modules = set(string_list_field(object_field(qt, "discovery"), "modules", ["QtCore", "QtGui", "QtWidgets"]))
        modules.update({"QtCore", "QtGui", "QtWidgets", "QtUiTools"})
        files = []
        for module in sorted(modules):
            matches = [root / module.lower() / (module.lower() + ".index") for root in roots]
            match = next((path for path in matches if path.is_file()), None)
            if match is None:
                raise ValueError(f"Qt {actual} QDoc index missing for {module}; cannot verify older API baseline")
            files.append(match)
    for path in files:
        if not path.is_file() or ET.parse(path).getroot().get("version") != actual:
            raise ValueError(f"API index must match scanning SDK Qt {actual}: {path}")
    return files


def apply_baseline(config: JsonObject, actual: str) -> None:
    """Add policy exclusions for APIs introduced after the requested Qt version.

    Header preprocessing still determines feature availability. QDoc supplies
    the introduction versions absent from many public header declarations,
    including property accessor methods. Unavailable overloads are excluded by
    signature, leaving older overloads of the same method available.
    """
    target: object = object_field(config, "qt").get("target_version")
    if not isinstance(target, str) or target == actual:
        return
    target_version = version_tuple(target)
    excluded = object_field(config, "exclude")
    classes = set(string_list_field(excluded, "classes"))
    members = set(string_list_field(excluded, "members"))
    for path in index_files(config, actual):
        root = ET.parse(path).getroot()
        for parent in root.iter():
            if parent.tag not in {"class", "namespace"}:
                continue
            owner = parent.get("fullname") or parent.get("name", "")
            since = parent.get("since")
            if parent.tag == "class" and since and version_tuple(since) > target_version:
                classes.add(owner)
            properties = {node.get("name", ""): node.get("since", "") for node in parent.findall("property")}
            for node in parent:
                since = node.get("since") or properties.get(node.get("associated-property", ""))
                if not since or version_tuple(since) <= target_version:
                    continue
                name = node.get("name", "")
                full = node.get("fullname") or f"{owner}::{name}"
                if node.tag == "function":
                    parameters = ",".join(p.get("type", "") for p in node.findall("parameter"))
                    members.add(f"{full}({parameters})")
                elif node.tag == "property":
                    members.add(full)
                    for accessor in node:
                        if accessor.tag in {"getter", "setter", "resetter"}:
                            members.add(f"{owner}::{accessor.get('name', '')}")
    excluded["classes"] = sorted(classes)
    excluded["members"] = sorted(members)
    config["exclude"] = excluded
