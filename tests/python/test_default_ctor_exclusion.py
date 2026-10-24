#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify exact zero-argument constructor exclusions in emitted Luau Definitions."""

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    """Verify exact zero-argument constructor exclusions in emitted Luau Definitions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--generator", type=pathlib.Path, required=True)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()
    subprocess.run(
        [
            sys.executable,
            "-m",
            str(args.generator),
            "--config",
            str(args.config),
            "--out",
            str(args.out),
        ],
        check=True,
    )
    text = (args.out / "qt.d.luau").read_text(encoding="utf-8")
    call = next((line for line in text.splitlines() if "    QPushButton:" in line), "")
    if "(() -> _qt_QPushButton)" in call:
        raise SystemExit("zero-argument QPushButton constructor still appears in Definition")
    if "((text: string | ustring) -> _qt_QPushButton)" not in call:
        raise SystemExit("text QPushButton constructor should remain available")
    print("default constructor Definition fixture passed")


if __name__ == "__main__":
    main()
