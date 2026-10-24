# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Check moc policy, precise overload exclusion and standalone definition generation."""

import copy
import json
import pathlib
import tempfile

from qtluau_codegen.extensions import definitions, emit_extensions
from qtluau_codegen.generate_definitions import generate
from qtluau_codegen.models import JsonObject


def main() -> None:
    """Check moc policy, precise overload exclusion and standalone definition generation."""
    fixture = pathlib.Path(__file__).resolve().parents[1] / "fixtures/extensions"
    config: JsonObject = json.loads((fixture / "bindings.json").read_text())
    with tempfile.TemporaryDirectory() as temporary:
        out = pathlib.Path(temporary)
        metadata = emit_extensions(config, out, fixture)
        service = next(entry for entry in metadata if entry["name"] == "ScriptService")
        methods = {method["name"] for method in service["methods"]}
        assert {"echo", "echoView", "kind", "roundtrip"} <= methods
        assert not {"hiddenSlot", "secret", "publicSlot"} & methods
        assert all("Qt 6." in path.read_text() for path in out.glob("qt_ext_moc_*.cpp"))
        definition = definitions(metadata)
        assert "extends _qt_QWidget" in definition and "_qt_QDialog" not in definition
        assert "isMemberExcluded" not in "".join(
            path.read_text() for path in out.glob("qt_ext_*.cpp")
        )
        narrowed = copy.deepcopy(config)
        narrowed["exclude"]["members"].append("ScriptService::kind(int)")
        narrowed["extensions"][0]["classes"]["ScriptService"]["constructible"] = False
        narrowed_metadata = emit_extensions(narrowed, out, fixture)
        service = next(entry for entry in narrowed_metadata if entry["name"] == "ScriptService")
        kinds = [method for method in service["methods"] if method["name"] == "kind"]
        assert len(kinds) == 1 and kinds[0]["parameters"] == ["string"]
        assert not service["constructible"]
        # Original policy is also sufficient for the standalone definition CLI path.
        generate(config, out / "definitions", fixture)
        assert "declare app:" in (out / "definitions/qtluau.d.luau").read_text()
        constructor_policy = copy.deepcopy(config)
        constructor_policy["exclude"]["members"].append("ScriptService::new(int)")
        constructor_metadata = emit_extensions(constructor_policy, out, fixture)
        assert next(entry for entry in constructor_metadata if entry["name"] == "ScriptService")[
            "constructible"
        ]
        constructor_policy["exclude"]["members"].append("ScriptService::new()")
        constructor_metadata = emit_extensions(constructor_policy, out, fixture)
        assert not next(
            entry for entry in constructor_metadata if entry["name"] == "ScriptService"
        )["constructible"]
        excluded = copy.deepcopy(config)
        excluded["exclude"]["classes"].append("ScriptService")
        without_service = emit_extensions(excluded, out, fixture)
        assert [entry["name"] for entry in without_service] == ["ScriptDialog"]
        integrated = copy.deepcopy(config)
        integrated["extensions"][0]["compile_moc"] = False
        emit_extensions(integrated, out, fixture)
        assert not list(out.glob("qt_ext_moc_*.cpp"))
        bad = copy.deepcopy(config)
        bad["extensions"][0]["classes"]["MissingClass"] = {}
        try:
            emit_extensions(bad, out, fixture)
        except ValueError as error:
            assert "absent from moc metadata" in str(error)
        else:
            raise AssertionError("Missing Q_OBJECT class was silently ignored")
    print("QObject extension policies and standalone definitions passed")


if __name__ == "__main__":
    main()
