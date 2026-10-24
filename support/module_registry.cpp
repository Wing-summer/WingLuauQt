// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/module_require.hpp"

namespace qtluau {
namespace {
int requireModule(lua_State *L) {
  if (lua_type(L, 1) == LUA_TSTRING) {
    size_t length = 0;
    const char *name = lua_tolstring(L, 1, &length);
    if (pushModule(L,
                   QAnyStringView(QUtf8StringView(name, qsizetype(length))))) {
      return 1;
    }
  }
  lua_pushvalue(L, lua_upvalueindex(1));
  lua_insert(L, 1);
  lua_call(L, lua_gettop(L) - 1, LUA_MULTRET);
  return lua_gettop(L);
}
} // namespace
void installModuleRequire(lua_State *L) {
  lua_getfield(L, LUA_REGISTRYINDEX, "qtluau.require.installed");
  const bool installed = lua_toboolean(L, -1);
  lua_pop(L, 1);
  if (installed) {
    return;
  }
  lua_getglobal(L, "require");
  lua_pushcclosure(L, requireModule, "require", 1);
  lua_setglobal(L, "require");
  lua_pushboolean(L, true);
  lua_setfield(L, LUA_REGISTRYINDEX, "qtluau.require.installed");
}
} // namespace qtluau
