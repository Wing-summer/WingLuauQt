# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Prepare local generator dependencies from pyproject.toml using only the stdlib."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast


def requirements(manifest: Path, development: bool) -> list[str]:
    """Read project dependency requirements and the optional development group."""
    document = cast(dict[str, object], tomllib.loads(manifest.read_text()))
    project = document.get("project")
    if not isinstance(project, dict):
        raise ValueError("The dependency manifest has no project table")
    record = cast(dict[str, object], project)
    dependencies = record.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise ValueError("Project dependencies must be an array")
    values = list(cast(list[object], dependencies))
    if development:
        groups = record.get("optional-dependencies")
        if not isinstance(groups, dict):
            raise ValueError("The development dependency group is missing")
        entries = cast(dict[str, object], groups).get("dev")
        if not isinstance(entries, list):
            raise ValueError("Development dependencies must be an array")
        values.extend(cast(list[object], entries))
    if not all(isinstance(value, str) for value in values):
        raise ValueError("Dependency requirements must be strings")
    return cast(list[str], values)


def probe(manifest: Path, development: bool) -> bool:
    """Check the exact distribution pins declared by the project manifest.

    Raises:
        ValueError: A dependency is not an exact pin supported by this bootstrap.
    """
    for requirement in requirements(manifest, development):
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^;\s]+)", requirement)
        if match is None:
            raise ValueError(f"Bootstrap dependencies must use exact pins: {requirement}")
        name, expected = match.groups()
        try:
            if importlib.metadata.version(name) != expected:
                return False
        except importlib.metadata.PackageNotFoundError:
            return False
    return True


def prepare(manifest: Path, environment: Path, development: bool, install: bool) -> Path:
    """Reuse a compatible interpreter or prepare a local environment.

    Installation uses uv when available and stdlib venv/pip otherwise. Installer
    output goes to stderr; stdout is reserved for the selected interpreter path.
    """
    if probe(manifest, development):
        return Path(sys.executable)
    required = requirements(manifest, development)
    if not install:
        raise ValueError(
            "Install the manifest dependencies in Python3_EXECUTABLE or enable bootstrap: "
            + ", ".join(required)
        )
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    command = [str(python), str(Path(__file__).resolve()), "--manifest", str(manifest), "--probe"]
    if development:
        command.append("--dev")
    if (
        python.is_file()
        and subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        == 0
    ):
        return python
    uv = shutil.which("uv")
    if not python.is_file():
        create = (
            [uv, "venv", "--python", sys.executable, str(environment)]
            if uv
            else [sys.executable, "-m", "venv", str(environment)]
        )
        subprocess.run(create, check=True, stdout=sys.stderr)
    installer = (
        [uv, "pip", "install", "--python", str(python)]
        if uv
        else [str(python), "-m", "pip", "install"]
    )
    settings = dict(os.environ, UV_CACHE_DIR=str(environment.parent / ".uv-cache"))
    subprocess.run([*installer, *required], check=True, stdout=sys.stderr, env=settings)
    subprocess.run(command, check=True, stdout=sys.stderr)
    return python


def main() -> int:
    """Expose dependency probing and preparation to CMake without package imports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--environment", type=Path)
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--no-install", action="store_true")
    args = parser.parse_args()
    manifest: Path = args.manifest.resolve()
    try:
        if args.probe:
            return 0 if probe(manifest, args.dev) else 1
        if args.environment is None:
            parser.error("--environment is required for preparation")
        print(prepare(manifest, args.environment.resolve(), args.dev, not args.no_install))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
