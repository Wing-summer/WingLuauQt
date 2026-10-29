# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Public display paths must follow the generated declaration model."""

import json
import unittest

from qtluau_codegen.definition_graph import DefinitionFiles
from qtluau_codegen.symbol_catalog import emit_symbol_catalog


class SymbolDisplayTests(unittest.TestCase):
    def test_non_qt_constructor_keeps_class_name(self) -> None:
        """Classify host constructors from their type model rather than a Qt prefix."""
        files = DefinitionFiles()
        emit_symbol_catalog(
            {"_ext_hex_HexPosition": "type _ext_hex_HexPosition = { line: number }"},
            {"hex": "{ HexPosition: (() -> _ext_hex_HexPosition) }"}, {"hex"},
            [], files, "Probe", {})
        items = [item for name, source in files.sources.items()
                 if name.startswith("Probe_symbols_")
                 for item in json.loads(source)["children"]]
        constructor = next(item for item in items if item["label"] == "HexPosition")
        self.assertEqual(constructor["kind"], "class")

    def test_alias_members_follow_naming_policy(self) -> None:
        """Resolve nested alias members using the same spelling as registration."""
        for style, expected, rejected in [("snake_case", "read_all", "readAll"),
                                          ("native", "readAll", "read_all")]:
            files = DefinitionFiles()
            emit_symbol_catalog(
                {"_qt_QDevice": "type _qt_QDevice = { readAll: (self: _qt_QDevice) -> string }"},
                {"filesystem": "{ file: { __call: (() -> _qt_QDevice) } }"}, {"filesystem"},
                [], files, "Probe", {}, naming_config={"naming": {"functions": style}})
            pages = [json.loads(source) for name, source in files.sources.items()
                     if name.startswith("Probe_symbols_")]
            labels = [item["label"] for page in pages for item in page["children"]]
            self.assertIn(expected, labels)
            self.assertNotIn(rejected, labels)

    def test_renamed_module_paths(self) -> None:
        """Derive display paths from exports, independently of internal type names."""
        for module in ("qt", "lkqt"):
            files = DefinitionFiles()
            emit_symbol_catalog(
                {"_qt_QWidget": "type _qt_QWidget = {}",
                 "_qt_Unexported": "type _qt_Unexported = {}"},
                {module: "{ QWidget: (() -> _qt_QWidget), make: () -> _qt_QWidget }"},
                set(), [], files, "Probe", {})
            names = json.loads(files.sources["Probe_symbols.json"])["type_display_names"]
            self.assertEqual(names["_qt_QWidget"], module + ".QWidget")
            self.assertEqual(names["_qt_Unexported"], "_qt_Unexported")
            pages = "\n".join(source for name, source in files.sources.items()
                              if name.startswith("Probe_symbols_"))
            self.assertIn(module + ".QWidget", pages)
            if module != "qt":
                self.assertNotIn('"qt.QWidget"', pages)

    def test_global_alias_precedes_required_module(self) -> None:
        """Keep global type aliases readable when a required module shares them."""
        files = DefinitionFiles()
        emit_symbol_catalog(
            {"_qt_QFile": "type _qt_QFile = {}"},
            {"lkqt": "{ QFile: (() -> _qt_QFile) }",
             "filesystem": "{ file: { __call: (() -> _qt_QFile) } }"},
            {"filesystem"}, [], files, "Probe", {})
        names = json.loads(files.sources["Probe_symbols.json"])["type_display_names"]
        self.assertEqual(names["_qt_QFile"], "filesystem.file")

    def test_public_paths(self) -> None:
        files = DefinitionFiles()
        types = {"_qt_QWidget": "type _qt_QWidget = {}",
                 "Instance": "type Instance = {}",
                 "CData": "type CData = {}"}
        declarations = {
            **types,
            "__WingLuauQtValue_qt": "type __WingLuauQtValue_qt = __CallableRoot",
            "__CallableRoot": "type __CallableRoot = { nested: __CallableNested }",
            "__CallableNested": "type __CallableNested = { widget: _qt_QWidget }",
        }
        emit_symbol_catalog(types, {"qt": "{ QWidget: (() -> _qt_QWidget), make: () -> _qt_QWidget }"}, set(), [], files, "Probe", {},
                            module_types={"cffi": ["Instance", "CData"]},
                            declaration_types=declarations)
        names = json.loads(files.sources["Probe_symbols.json"])["type_display_names"]
        self.assertEqual(names["_qt_QWidget"], "qt.QWidget")
        self.assertEqual(names["__CallableRoot"], "typeof(qt)")
        self.assertEqual(names["__CallableNested"], "typeof(qt.nested)")
        self.assertEqual(names["__WingLuauQtValue_qt"], "typeof(qt)")
        self.assertEqual(names["Instance"], "cffi.Instance")
        self.assertEqual(names["CData"], "cffi.CData")
        pages = "\n".join(value for key, value in files.sources.items()
                          if key.startswith("Probe_symbols_"))
        self.assertIn("qt.QWidget", pages)
        self.assertNotIn("_qt_QWidget", pages)


if __name__ == "__main__":
    unittest.main()
