# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Keep native type identities and same-arity overloads through module partitioning."""

import pathlib
import tempfile
import unittest

from qtluau_codegen.definition_graph import DefinitionFiles
from qtluau_codegen.luau_definitions import class_definition
from qtluau_codegen.module_definitions import module_definitions


class LuauDefinitionTests(unittest.TestCase):
    """Exercise the built-in renderer together with the framework's module boundaries."""

    def test_public_userdata_overloads_remain_nominal(self) -> None:
        """A configurable public name must survive overload grouping and partitioning."""
        source = class_definition("TextValue", [
            ("pick", [("value", "number")], "string"),
            ("pick", [("value", "string")], "number"),
        ], fields=[("length", "number")])
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            (directory / "common.d.luau").write_text(
                source + "\ndeclare text: (value: string) -> TextValue\n")
            (directory / "qt.d.luau").write_text(
                "type _qt_Network = { send: ((self: _qt_Network, value: string) -> ()) & "
                "((self: _qt_Network, value: number) -> ()) }\n"
                "declare qt: { socket: () -> _qt_Network }\n")
            files = DefinitionFiles()
            module_definitions(directory, [], files=files)
            declarations = "\n".join(files.sources.values())
        self.assertIn("declare extern type TextValue with", declarations)
        self.assertEqual(declarations.count("    pick:"), 2)
        self.assertIn("length:", declarations)
        self.assertIn("declare extern type _qt_Network with", declarations)
        self.assertNotIn("__WingLuauQtCallable_", declarations)


if __name__ == "__main__":
    unittest.main()
