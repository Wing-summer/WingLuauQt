# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Validate standalone export, access control and unordered definition-file maps."""

import argparse
import copy
import json
import pathlib
import subprocess
import tempfile

from qtluau_codegen.callback_bindings import emit_callbacks
from qtluau_codegen.cpp_literals import qt_string
from qtluau_codegen.extensions import emit_extensions
from qtluau_codegen.models import JsonObject
from qtluau_codegen.module_definitions import split_declarations
from qtluau_codegen.project import export_project
from qtluau_codegen.registration_codegen import emit_registrations


def main() -> None:
    """Validate standalone export, access control and unordered definition-file maps."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--definition-checker", type=pathlib.Path, required=True)
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[2]
    config: JsonObject = json.loads((root / "examples/bindings.json").read_text())
    try:
        export_project(config, root / "examples", root / "examples")
    except ValueError as error:
        assert "source roots" in str(error)
    else:
        raise AssertionError("Generator accepted overwriting native source root")
    legacy = copy.deepcopy(config)
    legacy["packages"] = ["application_module"]
    try:
        export_project(legacy, root / "build/rejected-policy", root / "examples")
    except ValueError as error:
        assert "extra_bindings" in str(error)
    else:
        raise AssertionError("Legacy fixed-package configuration was accepted")
    assert qt_string('中文"\\') == 'QString::fromUtf8("\\344\\270\\255\\346\\226\\207\\042\\134", 8)'
    invalid_boolean = copy.deepcopy(config)
    invalid_boolean.setdefault("qt", {}).setdefault("ui_tools", {})["enabled"] = "yes"
    try:
        with tempfile.TemporaryDirectory() as policy_output:
            emit_registrations(invalid_boolean, pathlib.Path(policy_output))
    except ValueError as error:
        assert "must be boolean" in str(error)
    else:
        raise AssertionError("Invalid runtime settings reached C++ generation")
    with tempfile.TemporaryDirectory() as temporary:
        out = pathlib.Path(temporary) / "project"
        manifest = export_project(config, out, root / "examples")
        stable_files = [out / "CMakeLists.txt", out / "include/generated_bindings.hpp", out / "modules/aggregate.cpp"]
        timestamps = [path.stat().st_mtime_ns for path in stable_files]
        (out / "binding_policy.json").write_text("obsolete resource")
        (out / "ExampleBindings_policy.qrc").write_text("obsolete resource")
        (out / "support/qt/config.cpp").write_text("obsolete parser")
        export_project(config, out, root / "examples")
        assert timestamps == [path.stat().st_mtime_ns for path in stable_files]
        assert (out / "support/execute_luau.cpp").is_file()
        assert (out / "support/module_registry.cpp").is_file()
        assert "executeScript" in (out / "include/generated_bindings.hpp").read_text()
        core = copy.deepcopy(config)
        core["project"].pop("helpers", None)
        core_out = pathlib.Path(temporary) / "core"
        export_project(config, core_out, root / "examples")
        core_manifest = export_project(core, core_out, root / "examples")
        assert core_manifest["helpers"] == []
        for optional_file in ("support/execute_luau.cpp", "support/module_registry.cpp",
                              "include/qtluau/execution.hpp", "include/qtluau/module_require.hpp"):
            assert not (core_out / optional_file).exists()
        assert (core_out / "include/qtluau/module_values.hpp").is_file()
        core_header = (core_out / "include/generated_bindings.hpp").read_text()
        assert "executeScript" not in core_header
        assert "installRequire = false" in core_header
        core_cpp = "\n".join(path.read_text() for path in (core_out / "modules").glob("*.cpp"))
        assert "executeLuau" not in core_cpp and "installModuleRequire" not in core_cpp
        core_cmake = (core_out / "CMakeLists.txt").read_text()
        assert "find_package(Qt6 REQUIRED" in core_cmake
        assert "Luau.Compiler" not in core_cmake

        assert set(manifest["modules"]) == {"", "qt", "app", "reader", "ctl"}
        assert "STATIC" in (out / "CMakeLists.txt").read_text()
        assert str(root) not in (out / "CMakeLists.txt").read_text()
        assert not (out / "runtime").exists()
        for header in (out / "include").rglob("*.hpp"):
            assert "#pragma once" not in header.read_text()
        assert "QTLUAU_GENERATED_" in (out / "include/generated_bindings.hpp").read_text()
        assert not (out / "modules.cpp").exists()
        assert {
            "aggregate.cpp",
            "definitions.cpp",
            "module_0_public.cpp",
            "module_1_app.cpp",
            "module_3_qt.cpp",
        } <= {p.name for p in (out / "modules").glob("*.cpp")}
        assert (
            "QHash<QString, QString> definitionFiles()"
            in (out / "include/generated_bindings.hpp").read_text()
        )
        assert (out / "native/api.hpp").is_file()
        assert "${_wingluauqt_input_root}/native/api.hpp" in (out / "generation_inputs.cmake").read_text()
        assert not list((out / "generated").glob("qt_ext_moc_*.cpp"))
        assert "AUTOMOC ON" in (out / "CMakeLists.txt").read_text()
        for source in (out / "generated").glob("*.cpp"):
            assert str(root / "examples/native") not in source.read_text()
        public_definition = (out / "definitions/module_0.d.luau").read_text()
        qt_definition = (out / "definitions/module_3.d.luau").read_text()
        assert public_definition.count("declare qt:") == 1
        assert "QPushButton:" in public_definition and "QtTools:" in public_definition
        assert "return (nil :: any) :: __WingLuauQtValue_qt" in qt_definition
        declarations = [out / "definitions" / f"module_{i}.d.luau" for i in range(5)]
        assert set((out / "definitions").glob("*.d.luau")) == set(declarations)
        assert sum(path.stat().st_size for path in declarations[1:]) < len(public_definition) // 10
        subprocess.run([
            str(args.definition_checker), "--merge", *map(str, declarations),
            "--probe=" + str(root / "examples/script.luau"),
        ], check=True)
        assert split_declarations("") == ([], [])
        aliases, values = split_declarations("type Tree = {children: {Tree}}\ndeclare tools: {root: Tree}\n")
        assert aliases == ["type Tree = {children: {Tree}}"]
        assert values == ["declare tools: {root: Tree}"]
        callback_definitions = emit_callbacks({"callback_sets": [{
            "name": "ModuleCallbacks", "module": "tools", "functions": [{
                "name": "echo", "native": "&ExampleCallbacks::echo", "parameters": [{"name": "value", "type": "string"}],
                "returns": ["string"]
            }]
        }]}, out / "generated")
        assert "qtluau::registerModuleCallbacks(L, {&ExampleCallbacks::echo});" in (out / "generated/callback_initializers.inc").read_text()
        callback_path = out / "callback-test.d.luau"
        callback_path.write_text(callback_definitions["tools"])
        subprocess.run([str(args.definition_checker), str(callback_path)], check=True)
        reference = copy.deepcopy(config)
        reference["project"]["native_mode"] = "reference"
        reference["project"]["host_targets"] = ["Host::Services"]
        for extension in reference["extensions"]:
            extension["compile_moc"] = False
        ref_out = pathlib.Path(temporary) / "referenced"
        export_project(reference, ref_out, root / "examples")
        assert not (ref_out / "native").exists()
        assert not list((ref_out / "generated").glob("qt_ext_moc_*.cpp"))
        assert "Host::Services" in (ref_out / "CMakeLists.txt").read_text()
        reference_cmake = (ref_out / "CMakeLists.txt").read_text()
        assert 'set(ExampleBindings_HOST_SOURCE_DIR "${CMAKE_SOURCE_DIR}" CACHE PATH' in reference_cmake
        assert str((root / "examples").resolve()) not in reference_cmake.split("find_package(Qt6", 1)[0]
        assert not (out / "adapters").exists()
        assert not (out / "generated/packages").exists()
        assert not list((out / "generated").glob("*.json"))
        assert not list((out / "generated").glob("*.yml"))
        assert not (out / "binding_policy.json").exists()
        assert not list(out.glob("*.qrc"))
        assert "qt_add_resources" not in (out / "CMakeLists.txt").read_text()
        assert not (out / "generated/registrations").exists()
        assert not (out / "support/qt/config.cpp").exists()
        assert not (out / "codegen/development_config.cpp").exists()
        assert not (out / "include/qtluau/config.hpp").exists()
        assert not (out / "include/qtluau/constructor_registration.hpp").exists()
        assert all("RegistrationConfig" not in header.read_text() for header in (out / "include").rglob("*.hpp"))
        assert not (out / "generated/default_widgets.inc").exists()
        assert "registerCommonBindings(L);" in (out / "modules/support.cpp").read_text()
        for source in [*out.glob("generated/static_*.cpp"), out / "modules/support.cpp"]:
            assert not any(token in source.read_text() for token in (
                "BindingConfig", "RegistrationConfig", "isMemberExcluded",
                "isConstructorExcluded", "isClassExcluded", "policy()",
            ))
        reader = public_definition.split("export type __WingLuauQtValue_reader = ", 1)[1].split("\n\n", 1)[0]
        assert "read_int:" in reader and "QObject" not in reader and "write_int:" not in reader
        wrong_context = copy.deepcopy(config)
        wrong_context["extensions"][-1]["classes"]["HostServices"]["context"] = []
        try:
            emit_extensions(wrong_context, out / "generated", root / "examples")
        except ValueError as error:
            assert "Unsupported member signature" in str(error)
        else:
            raise AssertionError("QObject sender pointer leaked into the script signature")
        denied = copy.deepcopy(config)
        denied["extensions"][1]["classes"]["InternalApi"].pop("non_public")
        try:
            emit_extensions(denied, out / "generated", root / "examples")
        except ValueError as error:
            assert "friend" in str(error)
        else:
            raise AssertionError("Private/protected C++ access was silently bypassed")
    print("Standalone project, access policy and compact shared definitions passed")


if __name__ == "__main__":
    main()
