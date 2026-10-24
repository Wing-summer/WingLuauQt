#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Verify that selecting QWidget alone does not export unselected widget classes or finders."""

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    """Verify that selecting QWidget alone does not export unselected widget classes or finders."""
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
    if "QPushButton:" in text or "QLabel:" in text:
        raise SystemExit("unselected widget class leaked into qt namespace")
    if "declare extern type _qt_QPushButton" in text or "declare extern type _qt_QLabel" in text:
        raise SystemExit("unselected widget class leaked into Definition closure")
    widget = text.split("declare extern type _qt_QWidget", 1)[1].split("\nend\n", 1)[0]
    for finder in ("find_child_push_button", "find_child_label"):
        if finder in widget:
            raise SystemExit(f"unselected child finder {finder} was emitted")
    print("selected-class boundary Definition fixture passed")


if __name__ == "__main__":
    main()
