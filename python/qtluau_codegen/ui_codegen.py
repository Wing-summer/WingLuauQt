# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

"""Generate the QUiLoader backend from selected widgets, SDK layouts and root policy."""

from __future__ import annotations

import json
from pathlib import Path

from .assets import support_root
from .discovery import scan
from .models import JsonObject, object_field, string_list_field
from .selection import matches


def emit_ui_loader(config: JsonObject, output: Path, widgets: list[str]) -> None:
    """Emit a static loader policy while retaining host resolver priority.

    Root class names are selection policy. Native central-widget operations and
    supported layouts are discovered, rather than maintained as C++ type lists.
    """
    classes, _ = scan(["QtCore", "QtGui", "QtWidgets"])
    defaults: JsonObject = json.loads((support_root() / "config/bindings.json").read_text())
    default_ui = object_field(object_field(defaults, "qt"), "ui_tools")
    ui = object_field(object_field(config, "qt"), "ui_tools")
    roots = string_list_field(ui, "root_classes", string_list_field(default_ui, "root_classes"))
    excluded = string_list_field(object_field(defaults, "exclude"), "classes") + string_list_field(
        object_field(config, "exclude"), "classes"
    )

    def inherits(name: str, base: str, seen: set[str] | None = None) -> bool:
        """Test native ancestry without revisiting a class."""
        seen = set() if seen is None else seen
        if name == base:
            return True
        if name in seen or name not in classes:
            return False
        seen.add(name)
        return any(inherits(parent, base, seen) for parent in classes[name]["bases"])

    for root in roots:
        if not inherits(root, "QWidget"):
            raise ValueError(
                f"UI root {root} is not an SDK widget; use the host resolver for custom classes"
            )
    layouts = sorted(
        name
        for name, record in classes.items()
        if inherits(name, "QLayout") and record["default_ctor"] and not matches(name, excluded)
    )
    reserved = sorted(
        set(widgets) | set(roots) | {name for name in classes if matches(name, excluded)}
    )

    def predicate(function: str, names: list[str]) -> str:
        """Emit a predicate with only the resolved names for this project."""
        expression = (
            " || ".join(f'name == QStringLiteral("{name}")' for name in sorted(set(names)))
            or "false"
        )
        return f"bool {function}(const QString &name) {{ return {expression}; }}"

    lines = [
        "// Copyright (c) 2026, wingsummer",
        "// SPDX-License-Identifier: BSD-3-Clause",
        "// Generated; do not edit.",
        '#include "qtluau/ui_support.hpp"',
        "#include <QApplication>",
        "#include <QBuffer>",
        "#include <QtWidgets/QtWidgets>",
        "#include <QtUiTools/QUiLoader>",
        "namespace qtluau::detail {",
        predicate("isUiClassReserved", reserved),
        "namespace {",
        predicate("allowedWidget", widgets),
        predicate("allowedLayout", layouts),
        predicate("allowedRoot", roots),
        "QWidget *adaptRoot(QWidget *loaded, QString *error) {",
    ]
    for root in roots:
        record = classes[root]
        central = next(
            (
                method
                for method in record["methods"]
                if method["name"].startswith("take")
                and not method["args"]
                and method["result"].replace(" ", "") == "QWidget*"
            ),
            None,
        )
        lines.append(f"if (auto *root = qobject_cast<{root} *>(loaded)) {{")
        if central is not None:
            lines += [
                f"auto *content = root->{central['name']}();",
                'if (!content) { delete root; if (error) { *error = QStringLiteral("UI root has no central widget"); } return nullptr; }',
                "content->setParent(nullptr);",
                "delete root;",
                "return content;",
            ]
        else:
            lines += [
                "root->setWindowFlags(Qt::Widget);",
                "root->setParent(nullptr);",
                "return root;",
            ]
        lines.append("}")
    lines += [
        "loaded->setParent(nullptr);",
        "return loaded;",
        "}",
        """class GeneratedUiLoader final : public QUiLoader {
  bool resolvedRoot_ = false;
public:
  explicit GeneratedUiLoader(const QDir &directory) { setWorkingDirectory(directory); }
  bool resolvedRoot() const { return resolvedRoot_; }
  QWidget *createWidget(const QString &type, QWidget *parent, const QString &name) override {
    if (auto resolver = uiResolver()) {
      const UiWidgetResult result = resolver({type, name, parent, !parent, availableWidgets().contains(type)});
      if (result.action == UiWidgetAction::Reject) { return nullptr; }
      if (result.action == UiWidgetAction::Use) {
        if (!result.widget) { return nullptr; }
        if (result.widget->parentWidget() != parent) { result.widget->setParent(parent); }
        result.widget->setObjectName(name);
        resolvedRoot_ = !parent || resolvedRoot_;
        return result.widget;
      }
    }
    if (auto factory = uiFactory(type)) {
      QWidget *widget = factory(parent);
      if (!widget) { return nullptr; }
      if (widget->parentWidget() != parent) { widget->setParent(parent); }
      widget->setObjectName(name);
      return widget;
    }
    if (!allowedWidget(type) && (parent || !allowedRoot(type))) { return nullptr; }
    return QUiLoader::createWidget(type, parent, name);
  }
  QLayout *createLayout(const QString &type, QObject *parent, const QString &name) override {
    return allowedLayout(type) ? QUiLoader::createLayout(type, parent, name) : nullptr;
  }
};
}
QWidget *loadUiDocument(const QByteArray &bytes, const QDir &directory, QString *error) {
  auto *app = qobject_cast<QApplication *>(QCoreApplication::instance());
  if (!app || QThread::currentThread() != app->thread()) {
    throw std::runtime_error("UI loading requires the host QApplication and GUI thread");
  }
  QByteArray data = bytes;
  QBuffer buffer(&data);
  if (!buffer.open(QIODevice::ReadOnly)) { throw std::runtime_error("Cannot open UI buffer"); }
  GeneratedUiLoader loader(directory);
  QWidget *root = loader.load(&buffer, nullptr);
  if (!root) {
    if (error) { *error = loader.errorString(); }
    return nullptr;
  }
  return loader.resolvedRoot() ? root : adaptRoot(root, error);
}
} // namespace qtluau::detail
""",
    ]
    (output / "ui_loader.cpp").write_text("\n".join(lines))
