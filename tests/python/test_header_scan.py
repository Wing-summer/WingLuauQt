#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Regression test for scanner output, overloads, namespace definitions and C++ syntax."""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

MOCK_BINDINGS = r"""#pragma once
#include <type_traits>
struct lua_State {};
namespace qtluau { template<class T> void guardClassMethods(lua_State*) {} }
namespace luabridge {
struct Namespace;
template <class T> struct Class {
    template <class Signature> Class& addConstructor() { return *this; }
    template <class... F> Class& addFunction(const char*, F&&...) { return *this; }
    template <class... F> Class& addStaticFunction(const char*, F&&...) { return *this; }
    template <class... F> Class& addProperty(const char*, F&&...) { return *this; }
    Namespace endClass();
};
struct Namespace {
    Namespace beginNamespace(const char*) const { return {}; }
    Namespace endNamespace() const { return {}; }
    template <class T> Class<T> beginClass(const char*) const { return {}; }
    template <class Derived, class Base, class... Bases> Class<Derived> deriveClass(const char*) const {
        static_assert(std::is_base_of_v<Base, Derived>);
        static_assert((std::is_base_of_v<Bases, Derived> && ...));
        return {};
    }
};
template <class T> Namespace Class<T>::endClass() { return {}; }
inline Namespace getGlobalNamespace(lua_State*) { return {}; }
}
"""


def main() -> None:
    """Regression test for scanner output, overloads, namespace definitions and C++ syntax."""
    p = argparse.ArgumentParser()
    p.add_argument("--scanner", type=pathlib.Path, required=True)
    p.add_argument("--fixtures", type=pathlib.Path, required=True)
    p.add_argument("--clang", default=shutil.which("clang++") or "clang++")
    p.add_argument("--definition-checker", type=pathlib.Path)
    a = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="qtluau-header-scan-") as temp:
        temp_path = pathlib.Path(temp)
        out = temp_path / "out"
        mock = temp_path / "mock"
        (mock / "qtluau").mkdir(parents=True)
        (mock / "qtluau" / "bindings.hpp").write_text(MOCK_BINDINGS, encoding="utf-8")
        subprocess.run(
            [
                sys.executable,
                "-m",
                str(a.scanner),
                "--input",
                str(a.fixtures),
                "--recursive",
                "--output",
                str(out),
                "--clang",
                a.clang,
            ],
            check=True,
        )
        required = [
            out / "a" / "value_binding.cpp",
            out / "b" / "value_binding.cpp",
            out / "common_binding.cpp",
        ]
        for path in required:
            if not path.is_file():
                raise SystemExit(f"expected independent generated file: {path}")

        a_cpp = (out / "a" / "value_binding.cpp").read_text(encoding="utf-8")
        a_def = (out / "a" / "value.d.luau").read_text(encoding="utf-8")
        if '"begin"' in a_cpp or '"end"' in a_cpp or "begin:" in a_def:
            raise SystemExit("C++ iterator API leaked into bindings")
        if "deriveClass<fixture::a::Value, fixture::Base>" not in a_cpp:
            raise SystemExit("public base class was not emitted as a LuaBridge3 derivation")
        if 'addFunction("number", static_cast<int (fixture::a::Value::*)() const>' not in a_cpp:
            raise SystemExit("missing first overload")
        if ", static_cast<int (fixture::a::Value::*)(int) const>" not in a_cpp:
            raise SystemExit("overloads were not registered as one LuaBridge3 overload group")
        if "_cpp_fixture__FromInclude" in a_def or "fromInclude" in a_def:
            raise SystemExit("a transitive include type leaked into the input header's output")
        if (
            "(() -> _cpp_fixture__a__Value)" not in (out / "all.d.luau").read_text()
            or "& ((arg1: number) -> _cpp_fixture__a__Value)"
            not in (out / "all.d.luau").read_text()
        ):
            raise SystemExit(
                "constructor overload signatures are not represented as an intersection"
            )
        abstract_body = a_def.split("declare extern type _cpp_fixture__a__Abstract", 1)[1].split(
            "\nend", 1
        )[0]
        if "__call:" in abstract_body:
            raise SystemExit("abstract class must not be emitted with a constructor")

        aggregator = (out / "register_all_scanned_bindings.cpp").read_text(encoding="utf-8")
        base_function = next(
            x["registration_function"]
            for x in json.loads((out / "binding_manifest.json").read_text(encoding="utf-8"))[
                "headers"
            ]
            if x["header"].endswith("common.h")
        )
        derived_function = next(
            x["registration_function"]
            for x in json.loads((out / "binding_manifest.json").read_text(encoding="utf-8"))[
                "headers"
            ]
            if x["header"].endswith("a/value.h")
        )
        if aggregator.index(base_function + "(L)") > aggregator.index(derived_function + "(L)"):
            raise SystemExit("base registration was not ordered before derived registration")
        all_def = (out / "all.d.luau").read_text(encoding="utf-8")
        if a.definition_checker:
            subprocess.run(
                [str(a.definition_checker.resolve()), str(out / "all.d.luau")],
                check=True,
            )
        if (
            "declare fixture: {" not in all_def
            or "FromInclude: ((" not in all_def
            or "a: {" not in all_def
        ):
            raise SystemExit("aggregate Definition did not create a merged namespace tree")

        manifest = json.loads((out / "binding_manifest.json").read_text(encoding="utf-8"))
        names = [item["registration_function"] for item in manifest["headers"]]
        if len(names) != len(set(names)):
            raise SystemExit("registration function names collided for equal basenames")

        # Syntax-check the generated C++ against a minimal LuaBridge shape. This does not replace a
        # real third-party build, but catches malformed C++ render output even on machines without Qt.
        cpp_files = sorted(out.rglob("*_binding.cpp")) + [out / "register_all_scanned_bindings.cpp"]
        for cpp in cpp_files:
            subprocess.run(
                [
                    a.clang,
                    "-std=c++17",
                    "-fsyntax-only",
                    f"-I{mock}",
                    f"-I{a.fixtures}",
                    str(cpp),
                ],
                check=True,
            )
    print("header scanner fixture passed")


if __name__ == "__main__":
    main()
