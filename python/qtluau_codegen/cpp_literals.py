# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Render explicit UTF-8 Qt literals for generated C++ sources."""

from collections.abc import Sequence


def qt_string(value: str) -> str:
    """Render an explicit UTF-8 QString expression, escaping arbitrary input bytes."""
    encoded = value.encode("utf-8")
    escaped = "".join(
        chr(byte) if 32 <= byte < 127 and byte not in (34, 92) else f"\\{byte:03o}"
        for byte in encoded
    )
    return f'QString::fromUtf8("{escaped}", {len(encoded)})'


def qt_list(values: Sequence[str]) -> str:
    """Render a QStringList initializer while preserving input order."""
    return "{" + ", ".join(qt_string(value) for value in dict.fromkeys(values)) + "}"
