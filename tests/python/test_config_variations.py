# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Exercise nondefault names and exposure policies across the export pipeline."""

import itertools
import json
import pathlib
import tempfile
import unittest

from qtluau_codegen.catalog import NATIVE_CLASSES
from qtluau_codegen.discovery import SDK_ENUMS, discover_sdk, scan
from qtluau_codegen.models import JsonObject
from qtluau_codegen.module_policy import qt_namespace
from qtluau_codegen.project import cpp_name, export_project
from qtluau_codegen.type_policy import common_types


class ConfigVariationTests(unittest.TestCase):
    """Keep configuration effective across registrations, definitions and catalogs."""

    def test_component_snapshots_are_isolated(self) -> None:
        """Switch SDK components in one process without leaking classes or enums."""
        modules = ["QtCore", "QtGui", "QtWidgets"]
        try:
            discover_sdk([*modules, "QtNetwork"])
        except ValueError:
            self.skipTest("QtNetwork SDK is not installed")
        root = pathlib.Path(__file__).resolve().parents[2]
        baseline, _ = scan(modules)
        self.assertNotIn("QTcpSocket", baseline)
        config: JsonObject = json.loads((root / "examples/network-sdk.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = pathlib.Path(directory)
            export_project(config, output / "network", root)
            self.assertIn("QTcpSocket", NATIVE_CLASSES)
            self.assertIn("QSsl::SslProtocol", SDK_ENUMS)
            self.assertNotIn("QTcpSocket", baseline)
            self.assertIn("Qt6::Network", (output / "network/CMakeLists.txt").read_text())
            dependencies = json.loads((output / "network/module_dependencies.json").read_text())
            self.assertIn("Network", dependencies["qt_components"])
            self.assertTrue(dependencies["modules"]["network"]["require"])
            self.assertIn("QTcpSocket", dependencies["modules"]["network"]["sdk_types"])
            export_project({"qt": {"widgets": {"include": ["QWidget"]}}}, output / "network", root)
            self.assertFalse(list((output / "network/generated/custom").glob("sdk_*.cpp")))
            self.assertNotIn("QTcpSocket", NATIVE_CLASSES)
            self.assertNotIn("QSsl::SslProtocol", SDK_ENUMS)
            self.assertNotIn("Qt6::Network", (output / "network/CMakeLists.txt").read_text())

    def test_invalid_names(self) -> None:
        """Reject invalid names before they reach generated C++, Luau or CMake."""
        for name in ("", "a.b", "end", "_G", "a\"b", "中文"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                qt_namespace({"qt": {"namespace": name}})
        for name in ("int", "constexpr", "requires", "co_await"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                cpp_name(name)
        with self.assertRaises(ValueError):
            common_types({"qt": {"namespace": "textvalue"},
                          "common": {"types": {"QString": {"alias": "textvalue"}}}})

    def test_export_variations(self) -> None:
        """Change independent options together, preserving paths and exposure."""
        root = pathlib.Path(__file__).resolve().parents[2]
        for required, ui_enabled in itertools.product((True, False), repeat=2):
            with self.subTest(required=required, ui_enabled=ui_enabled), tempfile.TemporaryDirectory() as temporary:
                output = pathlib.Path(temporary) / "nested output/library"
                config: JsonObject = {
                    "project": {"name": "RenamedBindings", "namespace": "renamed_bindings",
                                "definitions_directory": "types/custom", "helpers": []},
                    "qt": {"namespace": "lkqt", "widgets": {"include": ["QWidget"]},
                           "ui_tools": {"enabled": ui_enabled}},
                    "common": {"types": {"QString": {"alias": "textvalue"},
                                         "QByteArray": {"alias": "bytesvalue"},
                                         "QVariant": {"alias": "anyvalue"},
                                         "QColor": {"alias": "paintvalue"}}},
                    "modules": {"lkqt": {"require": required}},
                }
                export_project(config, output, root)
                code = "\n".join(path.read_text() for directory in ("generated", "modules")
                                 for path in (output / directory).rglob("*.cpp"))
                self.assertIn('beginNamespace("lkqt")', code)
                self.assertNotIn('beginNamespace("qt")', code)
                self.assertNotIn('lua_getglobal(L, "qt")', code)
                self.assertEqual('uiNamespace.addFunction("load_ui_widget_xml"' in code, ui_enabled)
                header = (output / "include/generated_bindings.hpp").read_text()
                self.assertIn("namespace renamed_bindings", header)
                self.assertIn("registerModule_lkqt", header)
                catalog = json.loads((output / "definitions/RenamedBindings_symbols.json").read_text())
                module = next(item for item in catalog["roots"] if item["label"] == "lkqt")
                self.assertEqual(module["require"], required)
                self.assertEqual(catalog["type_display_names"]["_qt_QWidget"], "lkqt.QWidget")
                definitions = "\n".join(path.read_text() for path in (output / "definitions").glob("*.d.luau"))
                self.assertIn("textvalue", definitions)
                self.assertNotIn("ustring", definitions)
                cmake = (output / "CMakeLists.txt").read_text()
                self.assertIn("add_library(RenamedBindings STATIC", cmake)
                self.assertIn("[=[types/custom]=]", cmake)
                self.assertFalse((output / "include/qtluau/execution.hpp").exists())
                self.assertIn("`registerModule_lkqt`", (output / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
