# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Keep SDK signal metadata, lazy dependencies and namespace aliases aligned."""

import pathlib
import tempfile
import unittest

from qtluau_codegen.catalog import NATIVE_CLASSES
from qtluau_codegen.discovery import SDK_ENUMS
from qtluau_codegen.framework_bindings import SdkBindings, emit_framework_bindings
from qtluau_codegen.models import JsonObject, NativeClass, NativeMethod


class SignalCodegenTests(unittest.TestCase):
    """Exercise generic facilities without maintaining a native socket API list."""

    def test_public_using_keeps_base_overloads(self) -> None:
        """Retain C++ using declarations while preserving normal name hiding."""
        base: NativeMethod = {"owner": "QUsingBase", "name": "bind", "result": "bool",
            "args": ["int"], "const": False, "static": False, "variadic": False, "deprecated": False}
        derived: NativeMethod = {**base, "owner": "QUsingChild", "args": ["bool"]}
        NATIVE_CLASSES["QUsingBase"] = {"source": "fixture.h", "bases": ["QObject"], "methods": [base],
            "abstract": False, "default_ctor": False, "dependencies": []}
        NATIVE_CLASSES["QUsingChild"] = {"source": "fixture.h", "bases": ["QUsingBase"], "methods": [derived],
            "using_methods": ["bind"], "abstract": False, "default_ctor": False, "dependencies": []}
        try:
            generator = SdkBindings({"sdk_bindings": {"class_adapters": {"QUsingChild": {"inherited_methods": True}}}})
            self.assertEqual([method["args"] for method in generator.methods("QUsingChild")], [["bool"], ["int"]])
            NATIVE_CLASSES["QUsingChild"]["using_methods"] = []
            self.assertEqual([method["args"] for method in generator.methods("QUsingChild")], [["bool"]])
        finally:
            del NATIVE_CLASSES["QUsingBase"]
            del NATIVE_CLASSES["QUsingChild"]

    def test_enum_constructor_precedes_integer(self) -> None:
        """Disambiguate enum constants without consuming arbitrary integer values."""
        name = "QEnumFixture"
        NATIVE_CLASSES[name] = {"source": "/sdk/QtExtra/qenumfixture.h", "bases": [],
            "methods": [], "abstract": False, "default_ctor": False,
            "constructors": [["unsigned int"], ["QEnumFixture::Mode"]], "dependencies": []}
        SDK_ENUMS[name + "::Mode"] = {"First": 1, "Second": 2}
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = pathlib.Path(directory)
                emit_framework_bindings({"sdk_bindings": {"modules": {"example": {"value": name}}}}, output)
                source = (output / "custom/sdk_QEnumFixture.cpp").read_text()
                self.assertLess(source.index("QtArgument<QEnumFixture::Mode, 1, 2>"),
                                source.index("unsigned int arg0"))
        finally:
            del NATIVE_CLASSES[name]
            del SDK_ENUMS[name + "::Mode"]

    def test_queued_snapshots_and_required_closure(self) -> None:
        """Emit safe parameter snapshots and register private dependencies on demand."""
        changed: NativeMethod = {"owner": "QSignalFixture", "name": "valueChanged",
            "result": "void", "args": ["const QString &", "bool"],
            "const": False, "static": False, "variadic": False,
            "deprecated": False, "signal": True}
        value: NativeClass = {"source": "/sdk/QtExtra/qvalue.h", "bases": [],
            "methods": [], "abstract": False, "default_ctor": True, "constructors": [[]],
            "dependencies": []}
        payload: NativeMethod = {**changed, "name": "payload", "signal": False, "args": [], "result": "QFixtureValue"}
        fixture: NativeClass = {"source": "/sdk/QtExtra/qfixture.h", "bases": ["QObject"],
            "methods": [changed, payload, {**changed, "name": "pendingAvailable", "args": ["QPrivateSignal"]}],
            "abstract": False, "default_ctor": True, "constructors": [[]], "dependencies": []}
        NATIVE_CLASSES["QSignalFixture"] = fixture
        NATIVE_CLASSES["QFixtureValue"] = value
        SDK_ENUMS["QFixtureEnums::Mode"] = {"Enabled": 1}
        try:
            config: JsonObject = {"qt": {"namespace": "widgets"},
                "sdk_bindings": {"modules": {"transport": {"fixture": "QSignalFixture"}},
                    "module_dependencies": {"transport": {"sdk_modules": ["QtExtra"]}},
                    "enum_namespaces": {"QFixtureEnums": {"module": "transport", "alias": "enums"}},
                    "class_adapters": {"QSignalFixture": {"context_owned": True}}},
                "modules": {"transport": {"require": True}}}
            with tempfile.TemporaryDirectory() as directory:
                output = pathlib.Path(directory)
                _, definitions = emit_framework_bindings(config, output)
                code = (output / "custom/sdk_QSignalFixture.cpp").read_text()
                self.assertIn("connectQueuedSignal", code)
                self.assertIn("&QSignalFixture::pendingAvailable", code)
                self.assertIn("[](auto &&...)", code)
                self.assertIn('signal: "pending_available", callback: () -> ()', definitions[""])
                self.assertIn("value0 = arg0", code)
                self.assertIn("value1 = arg1", code)
                self.assertNotIn('addFunction("valueChanged"', code)
                self.assertIn('signal: "value_changed"', definitions[""])
                self.assertIn("trackLuaObject(L, new QSignalFixture", code)
                self.assertIn("fixture_value:", definitions["transport"])
                self.assertIn("enums:", definitions["transport"])
                source = (output / "custom/sdk_modules.cpp").read_text()
                module = source.split("void registerSdkModule_transport(lua_State *L) {", 1)[1]
                self.assertIn("register_sdk_QFixtureValue(L)", module)
                self.assertIn("register_sdk_QSignalFixture(L)", module)
                self.assertIn("registerEnums_QFixtureEnums(L)", module)
                self.assertEqual(config["_sdk_public_types"], [])
        finally:
            del NATIVE_CLASSES["QSignalFixture"]
            del NATIVE_CLASSES["QFixtureValue"]
            del SDK_ENUMS["QFixtureEnums::Mode"]


if __name__ == "__main__":
    unittest.main()
