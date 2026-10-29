# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Exercise scanned host modules and compile-time guard selection without Qt scanning."""

import pathlib
import tempfile
import unittest

from qtluau_codegen.catalog import NATIVE_CLASSES
from qtluau_codegen.framework_bindings import SdkBindings, emit_framework_bindings
from qtluau_codegen.models import JsonObject, NativeMethod


def method(name: str, const: bool = False) -> NativeMethod:
    """Create an SDK-style method record for the isolated policy fixture."""
    return {"owner": "QSandboxDevice", "name": name, "result": "bool",
            "args": [], "const": const, "static": False,
            "variadic": False, "deprecated": False}


class SdkAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        """Install an isolated native record without replacing real SDK records."""
        self.had_qobject = "QObject" in NATIVE_CLASSES
        NATIVE_CLASSES.setdefault("QObject", {
            "source": "fixture.hpp", "bases": [], "methods": [],
            "abstract": False, "default_ctor": True, "dependencies": []})
        NATIVE_CLASSES["QSandboxDevice"] = {
            "source": "fixture.hpp", "bases": ["QObject"],
            "methods": [method("ready", True), method("open"), method("unknown")],
            "constructors": [[], ["bool"], ["bool", "QObject *"]],
            "abstract": False, "default_ctor": True,
            "dependencies": []}

    def tearDown(self) -> None:
        """Restore the shared scanner catalog after each fixture."""
        del NATIVE_CLASSES["QSandboxDevice"]
        if not self.had_qobject:
            del NATIVE_CLASSES["QObject"]

    def test_configured_type_aliases(self) -> None:
        """Apply configured common aliases to SDK arguments and native results."""
        for enabled, expected in [(True, "textvalue"), (False, "_qtluau_ustring")]:
            generator = SdkBindings({"common": {"types": {
                "QString": {"alias": "textvalue", "enabled": enabled}}},
                "_ustring_results": True})
            for spelling in ("QString", "const char *"):
                argument = generator.conversion(spelling, "QSandboxDevice")
                self.assertIsNotNone(argument)
                if argument is not None:
                    self.assertEqual(argument.lua, "string | " + expected)
            result = generator.conversion("QString", "QSandboxDevice", True)
            self.assertIsNotNone(result)
            if result is not None:
                self.assertEqual(result.lua, expected)

    def test_variant_reference_uses_type_identity(self) -> None:
        """Do not use a configurable QVariant constructor value as an instance type."""
        generator = SdkBindings({"common": {"types": {"QVariant": {"alias": "anyvalue"}}}})
        argument = generator.conversion("QVariant &", "QSandboxDevice")
        self.assertIsNotNone(argument)
        if argument is not None:
            self.assertEqual(argument.lua, "_qtluau_QVariant")
        generator = SdkBindings({"exclude": {"classes": ["QString"]}})
        self.assertEqual(generator.string_type, "_qtluau_ustring")

    def test_module_factory_and_typed_guards(self) -> None:
        config: JsonObject = {
            "qt": {"namespace": "lkqt"},
            "sdk_bindings": {
                "modules": {"devices": {"device": "QSandboxDevice"}},
                "class_adapters": {"QSandboxDevice": {
                    "includes": ["host/device.h"], "factory": "Host::create",
                    "guard": "Host::check", "guard_selector": "access",
                    "methods": {"open": "Host::open"}}},
                "guard_selectors": {"access": {
                    "const": "Host::Access::Read", "mutable": "Host::Access::Unknown",
                    "rules": [{"methods": ["open"], "value": "Host::Access::Open"}]}}}}
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary)
            _, definitions = emit_framework_bindings(config, output)
            code = (output / "custom/sdk_QSandboxDevice.cpp").read_text()
            self.assertIn('beginNamespace("lkqt")', code)
            self.assertIn("declare lkqt:", definitions["lkqt"])
            self.assertNotIn("qt", definitions)
            self.assertIn("Host::create()", code)
            self.assertIn("Host::check(Host::Access::Read, self.get())", code)
            self.assertIn("Host::check(Host::Access::Open, self.get())", code)
            self.assertIn("Host::check(Host::Access::Unknown, self.get())", code)
            self.assertIn("Host::open(self.get())", code)
            self.assertNotIn('Host::check("', code)
            self.assertIn("declare devices:", definitions["devices"])
            self.assertNotIn("arg0: boolean) ->", definitions["devices"])
            self.assertIn("arg1: _qt_QObject?", definitions["devices"])


if __name__ == "__main__":
    unittest.main()
