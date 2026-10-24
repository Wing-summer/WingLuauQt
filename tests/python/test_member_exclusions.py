#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Check that class/member/constructor exclusions also affect emitted Definitions."""

import argparse
import pathlib
import subprocess
import sys


def main() -> None:
    """Check that class/member/constructor exclusions also affect emitted Definitions."""
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
    text = (a.out / "qt.d.luau").read_text(encoding="utf-8")
    button = text.split("declare extern type _qt_QPushButton", 1)[1].split("\nend\n", 1)[0]
    widget = text.split("declare extern type _qt_QWidget", 1)[1].split("\nend\n", 1)[0]
    if any(line.lstrip().startswith(("function click(", "click:")) for line in button.splitlines()):
        raise SystemExit("excluded QPushButton::click still appears in Definition")
    if any("QPushButton:" in line and "text: string" in line for line in text.splitlines()):
        raise SystemExit("excluded QPushButton(QString) constructor still appears in Definition")
    if "set_text" not in button:
        raise SystemExit("unexcluded QPushButton::setText was removed")
    if "set_style_sheet" in widget:
        raise SystemExit("excluded QWidget::setStyleSheet still appears in Definition")
    if "find_child_push_button" not in widget:
        raise SystemExit("unexcluded typed child lookup was removed")
    child_fixture = a.out / "qt.d.luau"
    if not child_fixture.is_file():
        raise SystemExit("missing qt Definition output")
    for forbidden in (
        "QMainWindow:",
        "QDialog:",
        "QDockWidget:",
        "QFile:",
        "QThread:",
        "QProcess:",
        "QLibrary:",
        "QPluginLoader:",
        "QOpenGLWidget:",
    ):
        if forbidden in text:
            raise SystemExit(f"excluded class {forbidden[:-1]} still appears in Definition")
    if "move_to_thread" in text:
        raise SystemExit("QObject::moveToThread leaked into Definition")
    print("member/constructor exclusion fixture passed")


if __name__ == "__main__":
    main()
