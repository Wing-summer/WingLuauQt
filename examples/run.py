#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate, compile and test the independent static-library example."""

import argparse
import json
import pathlib
import subprocess

from qtluau_codegen.models import JsonObject
from qtluau_codegen.project import export_project


def main() -> None:
    """Run the complete generation, build and execution example."""
    root = pathlib.Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=pathlib.Path, default=root / "build")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--reference", action="store_true", help="Reuse host-owned classes and moc")
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    workdir: pathlib.Path = args.workdir.resolve()
    suffix = "-reference" if args.reference else ""
    output = workdir / ("example-project" + suffix)
    build = workdir / ("example-host" + suffix)
    config: JsonObject = json.loads((root / "examples/bindings.json").read_text())
    if args.reference:
        config["project"]["native_mode"] = "reference"
        config["project"]["host_targets"] = ["ExampleHostServices"]
        for entry in config["extensions"]:
            entry["compile_moc"] = False
    export_project(config, output, root / "examples")
    subprocess.run(
        [
            "cmake",
            "-S",
            str(root / "examples/host"),
            "-B",
            str(build),
            "-DBINDINGS_SOURCE_DIR=" + str(output),
            "-DHOST_NATIVE_REFERENCE=" + ("ON" if args.reference else "OFF"),
        ],
        check=True,
    )
    subprocess.run(["cmake", "--build", str(build), "--parallel", str(args.jobs)], check=True)
    subprocess.run(["ctest", "--test-dir", str(build), "--output-on-failure"], check=True)
    print(f"Generated project: {output}\nExample executable: {build / 'binding_example'}")


if __name__ == "__main__":
    main()
