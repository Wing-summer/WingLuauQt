# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Normalize generated headers to portable, deterministic include guards."""

from __future__ import annotations

import pathlib
import re


def guard_headers(root: pathlib.Path, project: str) -> None:
    """Replace pragma-once headers beneath root with project-qualified guards.

    Existing user-provided include guards are preserved. Generated guards are
    refreshed when an intermediate header is exported into a named project.
    """
    occupied: set[str] = set()
    for path in sorted(root.rglob("*")):
        if path.suffix not in {".h", ".hpp"} or not path.is_file():
            continue
        source = path.read_text()
        match = re.match(r"#ifndef (QTLUAU_GENERATED_[A-Z0-9_]+)\n#define \1\n", source)
        if match:
            source = source[match.end():]
            source = source.removesuffix(f"\n#endif // {match[1]}\n")
        elif "#pragma once" not in source:
            continue
        source = source.replace("#pragma once\n", "", 1)
        identity = project + "_" + path.relative_to(root).as_posix()
        macro = "QTLUAU_GENERATED_" + re.sub(r"[^A-Za-z0-9]", "_", identity).upper()
        if macro in occupied:
            raise ValueError(f"Duplicate generated include guard: {macro}")
        occupied.add(macro)
        result = f"#ifndef {macro}\n#define {macro}\n{source.rstrip()}\n\n#endif // {macro}\n"
        if path.read_text() != result:
            path.write_text(result)
