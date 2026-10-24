# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify the API baseline against the headers selected for Qt discovery."""

from __future__ import annotations

import pathlib
import re

from .api_baseline import index_files, version_tuple
from .discovery import discover_sdk
from .models import JsonObject, object_field


def selected_version() -> str:
    """Read Qt's version from the same include paths used by discovery.

    Raises:
        ValueError: The selected SDK does not provide a recognizable version.
    """
    for flag in discover_sdk(["QtCore"]):
        if not flag.startswith("-I"):
            continue
        root = pathlib.Path(flag[2:])
        for header in [root / "QtCore/qtcoreversion.h", root / "qtcoreversion.h"]:
            if header.is_file():
                match = re.search(r'#define\s+QTCORE_VERSION_STR\s+"(\d+\.\d+\.\d+)"', header.read_text())
                if match:
                    return match[1]
    raise ValueError("Cannot determine the selected Qt SDK version")


def validate_version(config: JsonObject) -> str:
    """Validate a configured API baseline against SDK and QDoc metadata.

    A newer header set requires matching QDoc indexes because Qt headers do
    not consistently annotate introduction versions. Missing metadata is an
    error rather than permission to export newer members.

    Args:
        config: Policy containing optional ``qt.target_version``.

    Returns:
        The target API version used for generation-time compatibility filtering.

    Raises:
        ValueError: The configured version is malformed or differs from the SDK.
    """
    actual = selected_version()
    target: object = object_field(config, "qt").get("target_version")
    if target is None:
        return actual
    if not isinstance(target, str) or not re.fullmatch(r"6\.\d+\.\d+", target):
        raise ValueError("qt.target_version must be a Qt 6 version such as 6.6.2")
    if version_tuple(target) > version_tuple(actual):
        raise ValueError(f"Qt API baseline {target} exceeds scanning SDK {actual}")
    if target != actual:
        index_files(config, actual)
    return target
