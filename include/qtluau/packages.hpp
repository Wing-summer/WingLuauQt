// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_PACKAGES_HPP
#define QTLUAU_INCLUDE_QTLUAU_PACKAGES_HPP

#include "qtluau/module_values.hpp"
#include "qtluau/value_conversion.hpp"

namespace qtluau {
// Package callbacks return (nil, error) after C++ temporaries are destroyed.
template <int (*Function)(lua_State *)> int packageCall(lua_State *L) {
  try {
    return Function(L);
  } catch (const std::exception &error) {
    lua_pushnil(L);
    lua_pushstring(L, error.what());
  }
  return 2;
}
inline void packageFunction(lua_State *L, const char *name,
                            lua_CFunction function) {
  lua_pushcfunction(L, function, name);
  lua_setfield(L, -2, name);
}
inline void packageNull(lua_State *L) {
  pushNullValue(L);
  lua_setfield(L, -2, "null");
}
inline QString packageText(lua_State *L, int index) {
  return qtFromLua<QString>(luabridge::LuaRef::fromStack(L, index));
}
inline QByteArray packageBytes(lua_State *L, int index) {
  return qtFromLua<QByteArray>(luabridge::LuaRef::fromStack(L, index));
}
} // namespace qtluau

#endif // QTLUAU_INCLUDE_QTLUAU_PACKAGES_HPP
