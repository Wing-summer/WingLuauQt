// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_MODULE_VALUES_HPP
#define QTLUAU_INCLUDE_QTLUAU_MODULE_VALUES_HPP

#include "qtluau/bindings.hpp"
#include <QByteArray>
#include <stdexcept>

namespace qtluau {
// Module values are handed to the host; this does not install a require
// function.
inline void rememberModule(lua_State *L, QAnyStringView name, int index) {
  if (name.isEmpty()) {
    throw std::invalid_argument("Public bindings are not a require module");
  }
  index = lua_absindex(L, index);
  lua_getfield(L, LUA_REGISTRYINDEX, "qtluau.modules");
  if (lua_isnil(L, -1)) {
    lua_pop(L, 1);
    lua_newtable(L);
    lua_pushvalue(L, -1);
    lua_setfield(L, LUA_REGISTRYINDEX, "qtluau.modules");
  }
  const QByteArray key = name.toString().toUtf8();
  lua_pushlstring(L, key.constData(), key.size());
  lua_pushvalue(L, index);
  lua_rawset(L, -3);
  lua_pop(L, 1);
}
inline bool pushModule(lua_State *L, QAnyStringView name) {
  lua_getfield(L, LUA_REGISTRYINDEX, "qtluau.modules");
  if (lua_istable(L, -1)) {
    const QByteArray key = name.toString().toUtf8();
    lua_pushlstring(L, key.constData(), key.size());
    lua_rawget(L, -2);
    lua_remove(L, -2);
    if (!lua_isnil(L, -1)) {
      return true;
    }
  }
  lua_pop(L, 1);
  return false;
}
} // namespace qtluau

#endif // QTLUAU_INCLUDE_QTLUAU_MODULE_VALUES_HPP
