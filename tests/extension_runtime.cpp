// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qt_extensions.hpp"
#include "qtluau/execution.hpp"
#include "static_registration.hpp"

#include "qtluau/widget_wrappers.hpp"
#include <QApplication>
#include <QPointer>
#include <iostream>

int main(int argc, char **argv) {
  QApplication app(argc, argv);
  lua_State *L = luaL_newstate();
  if (!L) {
    return 2;
  }
  int status = 0;
  try {
    luaL_openlibs(L);
    qtluau::registerCommonBindings(L);
    qtluau::registerQtBindings(L);
    QTLUAU_REGISTER_EXTENSIONS(L);
    QString error;
    const auto check = [&](QAnyStringView code) {
      if (!qtluau::executeLuau(L, code, &error)) {
        throw std::runtime_error(error.toStdString());
      }
    };
    check(R"(
            local service = app.ScriptService()
            assert(not pcall(function() service.echo_view() end))
            assert(not pcall(function() service.echo_view(nil, "x") end))
            assert(not pcall(function() service.echo_view({}, "x") end))
            assert(service:echo("世界") == "世界!")
            assert(service:echo_view("世界") == "世界")
            assert(service:echo("a\0b") == "a\0b!")
            assert(service:add(3, 4) == 7)
            assert(service:kind("abc") == "string")
            assert(service:kind(3) == "number")
            local data = service:roundtrip({name="Qt", values={1,2,3}})
            assert(data.name == "Qt" and data.values[3] == 3)
            assert(service:identity_map({name="container"}).name == "container")
            assert(service.secret == nil and service.public_slot == nil and service.hidden_slot == nil)
            local dialog = app.ScriptDialog()
            dialog:set_window_title("first")
            assert(dialog:title() == "first")
            dialog:rename("second")
            assert(dialog:window_title() == "second")
            assert(dialog.exec == nil and dialog.accept == nil)
        )");
    auto *borrowed = new ScriptService;
    qtluau::pushExtensionObject(L, borrowed);
    lua_setglobal(L, "borrowed");
    delete borrowed;
    check("assert(not pcall(function() borrowed:echo('x') end))");
    QPointer<ScriptService> owned = new ScriptService;
    qtluau::pushExtensionObject(L, owned.data(), true);
    lua_setglobal(L, "owned");
    check("owned = nil");
    lua_gc(L, LUA_GCCOLLECT, 0);
    if (owned) {
      throw std::runtime_error("Owned QObject was not released");
    }
    if (qtluau::toUtf8String(QAnyStringView(u"世界")) != "世界" ||
        qtluau::toQString("abc") != QStringLiteral("abc")) {
      throw std::runtime_error("String view conversion failed");
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    status = 1;
  }
  qtluau::clearLuaCallbacks(L);
  lua_close(L);
  return status;
}
