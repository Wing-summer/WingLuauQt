# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
"""Exercise configure reuse and invalidation through real CMake invocations."""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

_HELPER = pathlib.Path(__file__).resolve().parents[2] / "cmake/WingLuauQtGeneration.cmake"
_GENERATOR = r'''
import pathlib, sys, time
root = pathlib.Path(sys.argv[1])
count = root / 'count'
count.write_text(str(int(count.read_text()) + 1 if count.exists() else 1))
if (root / 'fail').exists():
    raise SystemExit(1)
time.sleep(0.05)
if (root / 'mutate').exists():
    (root / 'input.h').write_text('changed during generation')
    (root / 'mutate').unlink()
out = root / 'out'
out.mkdir(exist_ok=True)
(out / 'api.cpp').write_text('generated cpp')
(out / 'api.d.luau').write_text('generated definitions')
(out / 'watch.cmake').write_text(''' + "'''" + r'''
set(_wingluauqt_generation_inputs "${_wingluauqt_input_root}/dependency.h")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${_wingluauqt_generation_inputs})
set(_wingluauqt_generation_outputs
  "${CMAKE_CURRENT_LIST_DIR}/api.cpp"
  "${CMAKE_CURRENT_LIST_DIR}/api.d.luau"
  "${CMAKE_CURRENT_LIST_DIR}/watch.cmake")
''' + "'''" + r''')
'''


class GenerationCacheTests(unittest.TestCase):
    """Keep expensive generation conditional without hiding missing outputs."""

    def setUp(self) -> None:
        """Create a minimal SDK, host and generator with space-containing paths."""
        self.temporary = tempfile.TemporaryDirectory(prefix="qtluau cache ")
        self.root = pathlib.Path(self.temporary.name)
        for name in ("input.h", "dependency.h", "sdk.h"):
            (self.root / name).write_text("initial")
        (self.root / "generate.py").write_text(_GENERATOR)
        (self.root / "CMakeLists.txt").write_text(f'''
cmake_minimum_required(VERSION 3.24)
project(CacheFixture NONE)
include("{_HELPER.as_posix()}")
function(_wingluauqt_sdk_inputs files identity)
  set(${{files}} "${{CMAKE_CURRENT_SOURCE_DIR}}/sdk.h" PARENT_SCOPE)
  set(${{identity}} "${{TEST_SDK_VERSION}}" PARENT_SCOPE)
endfunction()
set(_outputs WATCH_FILE "${{CMAKE_CURRENT_SOURCE_DIR}}/out/watch.cmake")
if(TEST_GLOB_OUTPUTS)
  set(_outputs OUTPUT_GLOBS "${{CMAKE_CURRENT_SOURCE_DIR}}/out/*")
endif()
wingluauqt_cached_generation(
  OUTPUT_DIR "${{CMAKE_CURRENT_SOURCE_DIR}}/out" ROOT "${{CMAKE_CURRENT_SOURCE_DIR}}"
  ${{_outputs}}
  INPUTS "${{CMAKE_CURRENT_SOURCE_DIR}}/input.h" "${{CMAKE_CURRENT_SOURCE_DIR}}/generate.py"
  COMMAND "{pathlib.Path(sys.executable).as_posix()}" "${{CMAKE_CURRENT_SOURCE_DIR}}/generate.py" "${{CMAKE_CURRENT_SOURCE_DIR}}")
''')

    def tearDown(self) -> None:
        """Remove only the fixture-owned temporary tree."""
        self.temporary.cleanup()

    def configure(self, *options: str, success: bool = True) -> str:
        """Run CMake and return diagnostics, checking the expected exit status."""
        result = subprocess.run(
            ["cmake", "-S", str(self.root), "-B", str(self.root / "build"), "-G", "Ninja", *options],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def count(self) -> int:
        """Read how often the fake expensive generator actually ran."""
        return int((self.root / "count").read_text())

    def test_reuse_and_invalidation(self) -> None:
        """Detect input/SDK/output changes while ignoring touches and unrelated edits."""
        self.configure()
        stamp = (self.root / "out/api.cpp").stat().st_mtime_ns
        self.assertIn("reusing generated bindings", self.configure())
        (self.root / "input.h").touch()
        (self.root / "unrelated.cpp").write_text("unrelated")
        self.configure()
        self.assertEqual(self.count(), 1)
        self.assertEqual((self.root / "out/api.cpp").stat().st_mtime_ns, stamp)
        for name in ("dependency.h", "sdk.h", "input.h", "generate.py"):
            with (self.root / name).open("a") as file:
                file.write("\n# changed\n")
            self.configure()
        self.assertEqual(self.count(), 5)
        (self.root / "out/api.cpp").unlink()
        self.configure()
        (self.root / "out/api.d.luau").write_text("corrupted")
        self.configure()
        (self.root / "out/watch.cmake").unlink()
        self.configure()
        self.assertEqual(self.count(), 8)
        self.configure("-DTEST_SDK_VERSION=updated")
        self.assertEqual(self.count(), 9)
        self.configure("-DTEST_SDK_VERSION=updated")
        self.assertEqual(self.count(), 9)

    def test_failure_and_force(self) -> None:
        """Never checkpoint failed generation; provide an explicit force switch."""
        self.configure()
        previous = (self.root / ".out.configure.sha256").read_bytes()
        (self.root / "input.h").write_text("changed")
        (self.root / "fail").touch()
        self.configure(success=False)
        self.assertEqual((self.root / ".out.configure.sha256").read_bytes(), previous)
        (self.root / "fail").unlink()
        self.configure()
        self.assertEqual(self.count(), 3)
        self.configure("-DWINGLUAUQT_FORCE_GENERATION=ON")
        self.assertEqual(self.count(), 4)
        self.configure("-DWINGLUAUQT_FORCE_GENERATION=OFF")
        self.assertEqual(self.count(), 4)

    def test_standalone_output_glob(self) -> None:
        """Support standalone pipeline outputs without a project manifest."""
        self.configure("-DTEST_GLOB_OUTPUTS=ON")
        self.configure()
        self.assertEqual(self.count(), 1)
        (self.root / "out/api.cpp").unlink()
        self.configure()
        self.assertEqual(self.count(), 2)

    def test_changes_during_generation(self) -> None:
        """Do not cache output when its known inputs change during the scan."""
        (self.root / "mutate").touch()
        self.assertIn("checkpoint discarded", self.configure())
        self.assertFalse((self.root / ".out.configure.sha256").exists())
        self.configure()
        self.configure()
        self.assertEqual(self.count(), 2)

    def test_serialized_configures(self) -> None:
        """Share an output between build directories without duplicate generation."""
        commands = [["cmake", "-S", str(self.root), "-B", str(self.root / name), "-G", "Ninja"]
                    for name in ("build-a", "build-b")]
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                     for command in commands]
        try:
            for process in processes:
                output, _ = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, output)
            self.assertEqual(self.count(), 1)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()


if __name__ == "__main__":
    unittest.main()
