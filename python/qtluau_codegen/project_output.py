# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Serialize exports and publish complete generated files without intermediate state."""

from __future__ import annotations

import errno
import os
import pathlib
import shutil
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager

PROJECT_DIRECTORIES = ("generated", "include", "support", "modules", "native", "definitions", "adapters")


def project_directories(root: pathlib.Path) -> set[pathlib.Path]:
    """Find owned directories without visiting dependencies or version control."""
    result: set[pathlib.Path] = set()
    for name in PROJECT_DIRECTORIES:
        directory = root / name
        if directory.is_dir():
            result.add(pathlib.Path(name))
            result.update(path.relative_to(root) for path in directory.rglob("*")
                          if path.is_dir() and ".git" not in path.relative_to(root).parts)
    return result


def project_files(root: pathlib.Path) -> set[pathlib.Path]:
    """Select generated assets, excluding dependency checkouts and build trees."""
    if not root.exists():
        return set()
    files = {path.relative_to(root) for path in root.iterdir()
             if path.is_file() and (path.name in {"CMakeLists.txt", "README.md", "LICENSE"}
                                    or path.suffix in {".cmake", ".json", ".qrc"})}
    for directory in PROJECT_DIRECTORIES:
        files.update(path.relative_to(root) for path in (root / directory).rglob("*")
                     if path.is_file() and ".git" not in path.relative_to(root).parts)
    return files


@contextmanager
def project_output(output: pathlib.Path) -> Iterator[pathlib.Path]:
    """Stage a complete export under a cross-process output lock, then publish it.

    Existing compiler inputs stay readable throughout generation. A failed
    generation leaves the published project untouched. Unchanged files retain
    their timestamps; dependency checkouts and unrelated root files stay intact.
    """
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with (output.parent / ("." + output.name + ".generation.lock")).open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            if lock.seek(0, os.SEEK_END) == 0:
                lock.write(b"\0")
                lock.flush()
            while True:
                try:
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    time.sleep(0.1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            previous = project_files(output)
            previous_directories = project_directories(output)
            with tempfile.TemporaryDirectory(prefix="." + output.name + "-", dir=output.parent) as temporary:
                staging = pathlib.Path(temporary)
                for relative in previous:
                    target = staging / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(output / relative, target)
                yield staging
                expected = project_files(staging)
                for relative in sorted(expected):
                    source = staging / relative
                    target = output / relative
                    if target.is_file() and target.read_bytes() == source.read_bytes():
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    descriptor, filename = tempfile.mkstemp(prefix="." + target.name + "-", dir=target.parent)
                    os.close(descriptor)
                    try:
                        shutil.copy2(source, filename)
                        os.replace(filename, target)
                    finally:
                        pathlib.Path(filename).unlink(missing_ok=True)
                for relative in previous - expected:
                    (output / relative).unlink(missing_ok=True)
                obsolete = previous_directories - project_directories(staging)
                for relative in sorted(obsolete, key=lambda path: len(path.parts), reverse=True):
                    try:
                        (output / relative).rmdir()
                    except OSError as error:
                        if error.errno not in {errno.ENOTEMPTY, errno.EEXIST, errno.ENOENT}:
                            raise
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
