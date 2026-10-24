#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Validate variadic callback declarations with the target Luau parser."""

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    """Generate and parse variadic callback definitions from a regression policy."""
    p = argparse.ArgumentParser()
    p.add_argument("--generator", type=pathlib.Path, required=True)
    p.add_argument("--config", type=pathlib.Path, required=True)
    p.add_argument("--out", type=pathlib.Path, required=True)
    a = p.parse_args()
    subprocess.run(
        [
            sys.executable,
            "-m",
            str(a.generator),
            "--config",
            str(a.config),
            "--out",
            str(a.out),
        ],
        check=True,
    )
    text = (a.out / "generated_functions.d.luau").read_text(encoding="utf-8")
    required = [
        "declare function write_log(format: string, ...: any): ()",
        "declare function join_strings(prefix: string, ...: string): string",
        "declare function fixed_args(left: string, right: string): boolean",
    ]
    for s in required:
        if s not in text:
            raise SystemExit(f"missing expected signature: {s}")
    if "fixed_args(left: string, right: string, ...:" in text:
        raise SystemExit("fixed-arity function was incorrectly emitted as variadic")
    print("variadic Definition fixture passed")


if __name__ == "__main__":
    main()
