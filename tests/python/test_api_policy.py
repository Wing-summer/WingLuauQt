# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Check version filtering and registration/definition naming consistency."""

from __future__ import annotations

import pathlib
import tempfile

from qtluau_codegen.api_baseline import apply_baseline
from qtluau_codegen.function_naming import apply_function_naming, rename_declarations, snake_case
from qtluau_codegen.models import JsonObject, object_field, string_list_field


def main() -> None:
    """Exercise property introduction versions, overloads and class-name preservation."""
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        index = root / "widgets.index"
        index.write_text('''<INDEX version="6.12.0" project="QtWidgets">
<class name="QWidget"><function name="oldMethod" fullname="QWidget::oldMethod"/>
<property name="identifier" fullname="QWidget::identifier" since="6.9">
<getter name="identifier"/><setter name="setIdentifier"/></property>
<function name="setIdentifier" fullname="QWidget::setIdentifier" associated-property="identifier">
<parameter type="const QString &amp;"/></function>
<function name="overload" fullname="QWidget::overload" since="Qt 6.8">
<parameter type="int"/></function></class>
<class name="QNewWidget" since="6.10"/></INDEX>''')
        policy: JsonObject = {"qt": {"target_version": "6.6.2", "api_indexes": [str(index)]}}
        apply_baseline(policy, "6.12.0")
        exclusions = object_field(policy, "exclude")
        assert "QNewWidget" in string_list_field(exclusions, "classes")
        members = string_list_field(exclusions, "members")
        assert "QWidget::identifier" in members
        assert "QWidget::setIdentifier" in members
        assert "QWidget::overload(int)" in members
        assert "QWidget::oldMethod" not in members

        (root / "definitions").mkdir()
        definition = root / "definitions/module_0.d.luau"
        definition.write_text("declare qt: { QWidget: () -> Widget, getText: () -> string }\n")
        (root / "include/qtluau").mkdir(parents=True)
        (root / "include/qtluau/bindings.hpp").write_text("#ifndef TEST_BINDINGS_HPP\n#define TEST_BINDINGS_HPP\n#endif\n")
        code = root / "registration.cpp"
        code.write_text('cls.addFunction("getText", &Native::getText);\n')
        apply_function_naming({"naming": {"functions": "snake_case"}}, root)
        assert "QWidget:" in definition.read_text()
        assert "get_text:" in definition.read_text()
        assert "q_widget:" not in definition.read_text()
        assert 'functionName("getText")' in code.read_text()
        assert "&Native::getText" in code.read_text()
        assert snake_case("toUTF8") == "to_utf8"
        assert "get_text:" in rename_declarations({}, "declare qt: { getText: () -> string }")
        assert "getText:" in rename_declarations({"naming": {"functions": "native"}}, "declare qt: { getText: () -> string }")


if __name__ == "__main__":
    main()
