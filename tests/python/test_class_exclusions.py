#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Ensure excluded Qt classes cannot leak back through typed child lookup definitions."""

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    """Ensure excluded Qt classes cannot leak back through typed child lookup definitions."""
    p = argparse.ArgumentParser()
    p.add_argument("--generator", type=pathlib.Path, required=True)
    p.add_argument("--config", type=pathlib.Path, required=True)
    p.add_argument("--out", type=pathlib.Path, required=True)
    args = p.parse_args()
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
    if "QPushButton:" in text:
        raise SystemExit("excluded QPushButton remains exported from qt")
    if "declare extern type _qt_QPushButton" in text:
        raise SystemExit("excluded QPushButton remains in the Definition closure")
    widget = text.split("declare extern type _qt_QWidget", 1)[1].split("\nend\n", 1)[0]
    if "find_child_push_button" in widget:
        raise SystemExit("typed child lookup bypasses the excluded QPushButton class")
    print("class exclusion Definition fixture passed")


if __name__ == "__main__":
    main()
