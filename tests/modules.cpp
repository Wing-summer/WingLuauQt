// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/execution.hpp"
#include "qtluau/module_require.hpp"
#include "qtluau/packages.hpp"
#include <iostream>

int main() {
  lua_State *L = luaL_newstate();
  luaL_openlibs(L);
  lua_newtable(L);
  lua_pushinteger(L, 42);
  lua_setfield(L, -2, "answer");
  qtluau::rememberModule(L, "example", -1);
  lua_pop(L, 1);
  qtluau::installModuleRequire(L);
  qtluau::installModuleRequire(L);
  QString error;
  const bool passed = qtluau::executeLuau(L, QStringLiteral(R"LUA(
local example = require("example")
assert(example.answer == 42)
assert(example == require("example"))
assert(_G.example == nil)
assert(not pcall(require, "missing"))
)LUA"),
                                          &error);
  lua_State *other = luaL_newstate();
  const bool isolated = !qtluau::pushModule(other, "example");
  lua_close(other);
  lua_close(L);
  if (!passed || !isolated) {
    std::cerr << error.toStdString() << '\n';
    return 1;
  }
  return 0;
}
