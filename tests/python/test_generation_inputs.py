# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
"""Validate transitive source watchers and postprocessed output inventories."""

import pathlib
import subprocess
import tempfile
import unittest

from qtluau_codegen.models import JsonObject
from qtluau_codegen.project import generation_inputs


class GenerationInputsTests(unittest.TestCase):
    """Make cache sidecars complete and relocatable without watching host trees."""

    def test_dependencies_and_outputs(self) -> None:
        """Follow include cycles and inventory host-produced runtime/type files."""
        with tempfile.TemporaryDirectory(prefix="qtluau inputs ") as temporary:
            root = pathlib.Path(temporary)
            (root / "api.h").write_text('#include "dependency.h"\n')
            (root / "dependency.h").write_text('#include "api.h"\n#include <angled.h>\n')
            (root / "angled.h").write_text("literal angled include")
            (root / "unrelated.h").write_text("not an input")
            output = root / "out"
            (output / "generated").mkdir(parents=True)
            (output / "generated/host_api.luau").write_text("return {}")
            (output / "definitions").mkdir()
            (output / "definitions/host.d.luau").write_text("declare host: {}")
            config: JsonObject = {"native_apis": [{"headers": ["api.h"], "include_dirs": ["."]}]}
            generation_inputs(config, output, root)
            (root / "CMakeLists.txt").write_text('''
cmake_minimum_required(VERSION 3.24)
project(Inputs NONE)
set(_wingluauqt_input_root "${CMAKE_CURRENT_SOURCE_DIR}")
include("${CMAKE_CURRENT_SOURCE_DIR}/out/generation_inputs.cmake")
file(WRITE "${CMAKE_BINARY_DIR}/inputs.txt" "${_wingluauqt_generation_inputs}")
file(WRITE "${CMAKE_BINARY_DIR}/outputs.txt" "${_wingluauqt_generation_outputs}")
''')
            result = subprocess.run(["cmake", "-S", str(root), "-B", str(root / "build")],
                                    capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            inputs = set((root / "build/inputs.txt").read_text().split(";"))
            self.assertEqual(inputs, {str(root / "api.h"), str(root / "dependency.h"), str(root / "angled.h")})
            outputs = set((root / "build/outputs.txt").read_text().split(";"))
            self.assertEqual(outputs, {str(output / name) for name in (
                "generated/host_api.luau", "definitions/host.d.luau", "generation_inputs.cmake")})
            self.assertNotIn(str(root), (output / "generation_inputs.cmake").read_text())


if __name__ == "__main__":
    unittest.main()
