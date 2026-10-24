#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Prevent regressions in the Luau-before-LuaBridge3 include requirement."""

import argparse
from pathlib import Path


def main() -> int:
    """Prevent regressions in the Luau-before-LuaBridge3 include requirement."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    header = root / "include/qtluau/bindings.hpp"
    text = header.read_text(encoding="utf-8")
    required = [
        "#include <lua.h>",
        "#include <lualib.h>",
        "#include <LuaBridge/LuaBridge.h>",
    ]
    if "#include <lauxlib.h>" in text:
        raise SystemExit(
            "Luau has no lauxlib.h; this would include the incompatible system Lua header"
        )
    positions = [text.find(item) for item in required]
    if any(pos < 0 for pos in positions) or positions != sorted(positions):
        raise SystemExit(
            "Luau C API headers must all precede <LuaBridge/LuaBridge.h> in include/qtluau/bindings.hpp"
        )

    for directory in ("support", "adapters", "tests"):
        for path in (root / directory).rglob("*"):
            if not path.is_file() or path.suffix not in {".cpp", ".hpp", ".h"}:
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            if "LuaBridge/LuaBridge.h" in body and path != header:
                raise SystemExit(
                    f"{path.relative_to(root)} directly includes LuaBridge3; use qtluau/bindings.hpp to preserve Luau header order"
                )
    print("Luau/LuaBridge3 header-order fixture passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
