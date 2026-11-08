# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
"""Check opt-in caller-state forwarding without changing script signatures."""

import tempfile
import unittest
from pathlib import Path

from qtluau_codegen.models import JsonObject, object_list_field
from qtluau_codegen.native_apis import emit_native_apis


class NativeCallerTests(unittest.TestCase):
    """Exercise SDK scanning and callback emission with a small native API."""

    def generate(self, option: JsonObject) -> tuple[str, str, list[JsonObject]]:
        """Scan one defaulted function and return callbacks, source and metadata."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "api.h").write_text("int readValue(int offset = 1);\n", encoding="utf-8")
            config: JsonObject = {
                "native_apis": [
                    {
                        "headers": ["api.h"],
                        "functions": {"readValue": {}},
                        "groups": [{"namespace": "reader", **option}],
                    }
                ]
            }
            metadata = emit_native_apis(config, root, root)
            return (
                (root / "native_apis.hpp").read_text(),
                (root / "native_0_reader.cpp").read_text(),
                metadata,
            )

    def test_default_disabled(self) -> None:
        """Retain the existing callback contract unless explicitly enabled."""
        header, source, metadata = self.generate({})
        self.assertIn("std::function<int(int)> readValue", header)
        self.assertIn("function(1)", source)
        self.assertIs(metadata[0]["pass_lua_state"], False)

    def test_enabled(self) -> None:
        """Forward L after native arguments while retaining default overloads."""
        header, source, metadata = self.generate({"pass_lua_state": True})
        self.assertIn("std::function<int(int, lua_State *)> readValue", header)
        self.assertIn("function(1, L)", source)
        self.assertIn("function(arg0, L)", source)
        methods = object_list_field(metadata[0], "methods")
        self.assertEqual([m["parameters"] for m in methods], [[], ["number"]])
        self.assertEqual([m["result"] for m in methods], ["number", "number"])

    def test_url_sequences(self) -> None:
        """Expose Qt URL sequences as typed tables through the existing codec."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "api.h").write_text(
                "#include <QList>\n#include <QUrl>\n"
                "QList<QUrl> openedFiles();\n"
                "bool takeFiles(const QList<QUrl> &files);\n"
            )
            config: JsonObject = {"native_apis": [{
                "headers": ["api.h"],
                "functions": {"openedFiles": {}, "takeFiles": {}},
                "groups": [{"namespace": "reader"}],
            }]}
            metadata = emit_native_apis(config, root, root)
            methods = {m["native_name"]: m for m in object_list_field(metadata[0], "methods")}
            self.assertEqual(methods["openedFiles"]["result"], "{_qt_QUrl}")
            self.assertEqual(methods["takeFiles"]["parameters"], ["{_qt_QUrl}"])
            source = (root / "native_0_reader.cpp").read_text()
            self.assertIn("return qtToLua(L, result)", source)
            self.assertIn("QtArgument<QList<QUrl>>", source)

    def test_reject_non_boolean(self) -> None:
        """Reject string flags instead of silently enabling caller forwarding."""
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            self.generate({"pass_lua_state": "true"})


if __name__ == "__main__":
    unittest.main()
