#!/usr/bin/env python3
# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Exercise policy against real SDK AST, and compare emitted runtime/declaration metadata."""

import copy
import json
import pathlib
import tempfile

from qtluau_codegen.generate_definitions import generate
from qtluau_codegen.models import JsonObject
from qtluau_codegen.qt_pipeline import emit
from qtluau_codegen.type_policy import common_types


def main() -> None:
    """Exercise policy against real SDK AST, and compare emitted runtime/declaration metadata."""
    root = pathlib.Path(__file__).resolve().parents[2]
    config = json.loads((root / "config/bindings.json").read_text())
    with tempfile.TemporaryDirectory() as temp:
        out = pathlib.Path(temp)
        # Invalid nested configuration should fail with a useful validation error,
        # rather than leaking a dynamic attribute error from a chained get().
        malformed: list[JsonObject] = [
            {"lsp": "invalid"},
            {"common": []},
            {"qt": {"widgets": "invalid"}},
        ]
        for invalid in malformed:
            try:
                emit(invalid, out / "invalid")
            except ValueError as error:
                assert "must be an object" in str(error)
            else:
                raise AssertionError("Non-object policy was accepted")
        resolved = emit(config, out)
        assert "QTextEdit" in (out / "static_widgets.cpp").read_text()
        assert all("isMemberExcluded" not in path.read_text() for path in out.glob("qt_auto_*.cpp"))
        excluded_config = copy.deepcopy(config)
        excluded_config.setdefault("exclude", {}).setdefault("members", []).append(
            "QWidget::setFont"
        )
        filtered = emit(excluded_config, out / "filtered")
        assert not any(
            method[0] == "setFont"
            for method in filtered["_generated"]["types"]["QWidget"]["methods"]
        )
        assert 'cls.addFunction("set_font"' not in (out / "filtered/qt_auto_QWidget.cpp").read_text()
        assert '"find_child_push_button"' in (out / "static_widgets.cpp").read_text()
        assert not (out / "qt_widgets.inc").exists()
        assert "beginClass<QStringList>" not in (out / "static_widgets.cpp").read_text()
        minimal = emit({"qt": {"widgets": {"include": ["QWidget"]}}}, out / "minimal")
        assert minimal["qt"]["widgets"]["include"] == ["QWidget"]
        assert "beginClass<QStringList>" not in (out / "minimal/static_widgets.cpp").read_text()
        report = json.loads((out / "discovery-report.json").read_text())
        assert "QPushButton" in report["selected"]
        assert 'QStringLiteral("QColumnView")' in (out / "ui_loader.cpp").read_text()
        assert not (out / "qt_ui_widgets.inc").exists()
        assert "QMainWindow" not in report["selected"]
        assert "QDialog" not in report["selected"]
        assert "QFont" in report["dependencies"] and "QColor" in report["dependencies"]
        assert resolved["_generated"]["types"]["QPushButton"]["methods"]
        assert any(m[0] == "setFont" for m in resolved["_generated"]["types"]["QWidget"]["methods"])
        backend = json.loads((out / "qt_tsujikiri.input.yml").read_text())
        assert pathlib.Path(backend["source"]["path"]).is_file()
        generate(resolved, out / "definitions")
        qt = (out / "definitions/qt.d.luau").read_text()
        assert "set_font" in qt and "_qt_QFont" in qt
        assert "QMainWindow:" not in qt
        assert "add_items:" in qt and "item_data:" in qt
        assert "begin:" not in qt and "constBegin:" not in qt
        aliases = copy.deepcopy(resolved)
        aliases["common"]["types"]["QVariant"]["alias"] = "boxed"
        assert common_types(aliases)["QVariant"]["alias"] == "boxed"
        generate(aliases, out / "aliases")
        assert "declare boxed:" in (out / "aliases/common.d.luau").read_text()
        for container in (
            "QStringList",
            "QVariantList",
            "QVariantMap",
            "QVariantHash",
            "QList<int>",
            "QMap<QString, int>",
        ):
            for invalid in (
                {"common": {"types": {container: {"alias": "items"}}}},
                {"qt": {"widgets": {"include": [container]}}},
            ):
                try:
                    emit(invalid, out / "invalid-container")
                except ValueError as error:
                    assert "table" in str(error)
                else:
                    raise AssertionError(f"Container alias/class was accepted: {container}")
        common = (out / "definitions/common.d.luau").read_text()
        assert all(
            f"declare {alias}:" not in common
            for alias in ("stringlist", "variantlist", "variantmap")
        )
        # Common capability selection must affect the generated API.
        restricted = copy.deepcopy(resolved)
        restricted["common"]["types"]["QString"]["methods"] = ["length"]
        restricted["common"]["types"]["QByteArray"]["enabled"] = False
        generate(restricted, out / "restricted")
        common = (out / "restricted/common.d.luau").read_text()
        ustring = common.split("declare extern type ustring", 1)[1].split("\nend", 1)[0]
        assert "function length" in ustring and "function append" not in ustring
        assert "QByteArray:" not in (out / "restricted/qt.d.luau").read_text()
    print("Qt discovery, dependencies and capabilities passed")


if __name__ == "__main__":
    main()
