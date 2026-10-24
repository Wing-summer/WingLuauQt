// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include <QApplication>
#include <QDialog>
#include <QFile>
#include <QMainWindow>
#include <QPointer>
#include <generated_bindings.hpp>
#include <iostream>
#include <stdexcept>

int main(int argc, char **argv) {
  QApplication application(argc, argv);
  lua_State *L = luaL_newstate();
  if (!L)
    return 2;
  int status = 0;
  try {
    luaL_openlibs(L);
    example_bindings::registerPublicModule(L);
    lua_getglobal(L, "PublicApi");
    if (!lua_istable(L, -1))
      throw std::runtime_error("Public module was not registered");
    lua_pop(L, 1);
    lua_getglobal(L, "app");
    if (!lua_isnil(L, -1))
      throw std::runtime_error("App module registered too early");
    lua_pop(L, 1);
    example_bindings::registerModule_qt(L);
    example_bindings::registerModule_app(L);
    example_bindings::registerAllModules(
        L); // repeated registration is idempotent
    HostServices services;
    QObject scriptSession;
    example_bindings::bind_reader_Reader(L, &services, &scriptSession);
    example_bindings::bind_ctl_Control(L, &services, &scriptSession);
    auto definitions = example_bindings::definitionFiles();
    definitions.insert(example_bindings::moduleFiles());
    for (const QString &module :
         {QString(), QStringLiteral("qt"), QStringLiteral("app")}) {
      QFile file(definitions.value(module));
      if (!file.open(QIODevice::ReadOnly) || file.readAll().isEmpty())
        throw std::runtime_error("Copied module definition is missing");
    }
    QString error;
    QFile script(QStringLiteral(EXAMPLE_SCRIPT_PATH));
    if (!script.open(QIODevice::ReadOnly))
      throw std::runtime_error("Cannot read example script");
    if (!example_bindings::executeScript(L, QAnyStringView(script.readAll()),
                                         &error))
      throw std::runtime_error(error.toStdString());
    auto *shortLivedSession = new QObject;
    example_bindings::bind_reader_Reader(L, &services, shortLivedSession);
    delete shortLivedSession;
    if (!example_bindings::executeScript(L, "assert(not pcall(reader.readInt))",
                                         &error))
      throw std::runtime_error("Deleted context was not rejected");
    auto *shortLivedService = new HostServices;
    example_bindings::bind_reader_Reader(L, shortLivedService, &scriptSession);
    delete shortLivedService;
    if (!example_bindings::executeScript(L, "assert(not pcall(reader.readInt))",
                                         &error))
      throw std::runtime_error("Deleted service was not rejected");
    int resolved = 0;
    qtluau::setUiWidgetResolver(
        [&](const qtluau::UiWidgetRequest &request) -> qtluau::UiWidgetResult {
          if (!request.isRoot)
            return {};
          ++resolved;
          if (request.className == QStringLiteral("QMainWindow"))
            return {qtluau::UiWidgetAction::Use, new QMainWindow};
          if (request.className == QStringLiteral("QDialog"))
            return {qtluau::UiWidgetAction::Use, new ExampleDialog};
          if (request.className == QStringLiteral("QWidget"))
            return {qtluau::UiWidgetAction::Use, new ExampleDialog};
          if (request.className == QStringLiteral("UnknownWindow"))
            return {qtluau::UiWidgetAction::Use, new QWidget};
          if (request.className == QStringLiteral("DeniedWindow"))
            return {qtluau::UiWidgetAction::Reject, nullptr};
          return {};
        });
    for (const QString &name :
         {QStringLiteral("QMainWindow"), QStringLiteral("QDialog"),
          QStringLiteral("QWidget"), QStringLiteral("UnknownWindow")}) {
      const QByteArray xml =
          "<ui version=\"4.0\"><class>Test</class><widget class=\"" +
          name.toUtf8() + "\" name=\"root\"/></ui>";
      std::unique_ptr<QWidget> widget(
          qtluau::loadUiWidgetXmlNative(xml, &error));
      if (!widget || widget->objectName() != QStringLiteral("root"))
        throw std::runtime_error(error.toStdString());
      if (name == QStringLiteral("QMainWindow") &&
          !qobject_cast<QMainWindow *>(widget.get()))
        throw std::runtime_error("Host QMainWindow root was converted");
      if (name == QStringLiteral("QDialog") &&
          !qobject_cast<ExampleDialog *>(widget.get()))
        throw std::runtime_error("Host dialog type was not preserved");
    }
    std::unique_ptr<QWidget> rejected(qtluau::loadUiWidgetXmlNative(
        "<ui version=\"4.0\"><class>Test</class><widget class=\"DeniedWindow\" "
        "name=\"root\"/></ui>",
        &error));
    if (rejected || resolved != 5)
      throw std::runtime_error("UI resolver policy was ignored");
    qtluau::setUiWidgetResolver({});
    std::cout << "Public, qt and app modules; embedded definitions; Lua "
                 "execution; UI callbacks passed\n";
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    status = 1;
  }
  qtluau::setUiWidgetResolver({});
  qtluau::clearLuaCallbacks(L);
  lua_close(L);
  return status;
}
