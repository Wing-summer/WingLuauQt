// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "generated_bindings.hpp"
#include <QApplication>
#include <QFile>
#include <QLabel>
#include <QMenu>
#include <QTextEdit>
#include <iostream>

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  auto *L = luaL_newstate();
  int result = 0;
  try {
    luaL_openlibs(L);
    editor_bindings::registerAllModules(L);
    for (const auto &path : editor_bindings::definitionFiles()) {
      if (path.startsWith(QStringLiteral(":")) || !QFile::exists(path)) {
        throw std::runtime_error("CMake did not copy a definition file");
      }
    }
    QFile source(QStringLiteral(EDITOR_SCRIPT));
    if (!source.open(QIODevice::ReadOnly)) {
      throw std::runtime_error("Cannot read editor script");
    }
    QString error;
    auto *script = lua_newthread(L);
    if (!editor_bindings::executeScript(
            script, QUtf8StringView(source.readAll()), &error)) {
      throw std::runtime_error(error.toStdString());
    }
    lua_pop(L, 1);
    lua_gc(L, LUA_GCCOLLECT, 0);
    const bool smoke = app.arguments().contains(QStringLiteral("--smoke"));
    if (smoke) {
      QWidget *window = nullptr;
      for (auto *candidate : QApplication::topLevelWidgets()) {
        if (candidate->objectName() == QStringLiteral("editor-window")) {
          window = candidate;
        }
      }
      if (!window) {
        throw std::runtime_error("Editor window was not created");
      }
      auto *menu = window->findChild<QMenu *>(QStringLiteral("file-menu"));
      auto *text =
          window->findChild<QTextEdit *>(QStringLiteral("editor-text"));
      auto *status =
          window->findChild<QLabel *>(QStringLiteral("editor-status"));
      if (!menu || !text || !status || menu->actions().size() != 3) {
        throw std::runtime_error("Editor menu or controls missing");
      }
      if (!(menu->windowFlags() & Qt::Popup)) {
        throw std::runtime_error("Menu lost its popup flags during parenting");
      }
      menu->actions().at(1)->trigger();
      if (text->toPlainText() != QStringLiteral("Hello from Luau") ||
          status->text() != QStringLiteral("Sample inserted")) {
        throw std::runtime_error("Sample menu callback failed");
      }
      menu->actions().at(0)->trigger();
      if (!text->toPlainText().isEmpty() ||
          status->text() != QStringLiteral("New document")) {
        throw std::runtime_error("New menu callback failed");
      }
      menu->actions().at(2)->trigger();
      if (window->isVisible()) {
        throw std::runtime_error("Close menu callback failed");
      }
    } else {
      result = app.exec();
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    result = 1;
  }
  qtluau::clearLuaCallbacks(L);
  lua_close(L);
  return result;
}
