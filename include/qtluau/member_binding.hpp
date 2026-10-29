// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef WINGLUAUQT_INCLUDE_QTLUAU_MEMBER_BINDING_HPP
#define WINGLUAUQT_INCLUDE_QTLUAU_MEMBER_BINDING_HPP

#include <initializer_list>

namespace qtluau {
namespace detail {
template <class T> int checkedMethodCall(lua_State *L) {
  // Check before LuaBridge computes absolute indices or decodes native
  // arguments.
  if (lua_gettop(L) == 0 || lua_type(L, 1) != LUA_TUSERDATA ||
      !luabridge::Stack<const T *>::isInstance(L, 1)) {
    luaL_error(L, "Invalid method receiver; use object:method(...) or "
                  "object.method(object, ...)");
  }
  const int arguments = lua_gettop(L);
  lua_pushvalue(L, lua_upvalueindex(1));
  lua_insert(L, 1);
  lua_call(L, arguments, LUA_MULTRET);
  return lua_gettop(L);
}

template <class T>
luabridge::LuaRef staticClassFunction(const luabridge::LuaRef &key,
                                    lua_State *state) {
  lua_rawgetp(state, LUA_REGISTRYINDEX,
             const_cast<void *>(luabridge::detail::getStaticRegistryKey<T>()));
  key.push(state);
  lua_rawget(state, -2);
  auto result = luabridge::LuaRef::fromStack(state, -1);
  lua_pop(state, 2);
  return result.isFunction() ? result : luabridge::LuaRef(state);
}
} // namespace detail

// Wrap only instance methods. Constructors, module functions, properties and
// metamethods retain their original calling conventions.
template <class T> void guardClassMethods(lua_State *L) {
  for (const void *key : {luabridge::detail::getClassRegistryKey<T>(),
                          luabridge::detail::getConstRegistryKey<T>()}) {
    lua_rawgetp(L, LUA_REGISTRYINDEX, const_cast<void *>(key));
    if (lua_istable(L, -1)) {
      const int table = lua_gettop(L);
      lua_pushnil(L);
      while (lua_next(L, table)) {
        if (lua_type(L, -2) == LUA_TSTRING && lua_isfunction(L, -1)) {
          const char *name = lua_tostring(L, -2);
          if (!(name[0] == '_' && name[1] == '_') &&
              (!lua_iscfunction(L, -1) ||
               lua_tocfunction(L, -1) != &detail::checkedMethodCall<T>)) {
            lua_pushvalue(L, -2);
            lua_pushvalue(L, -2);
            lua_pushcclosure(L, &detail::checkedMethodCall<T>, name, 1);
            lua_rawset(L, table);
          }
        }
        lua_pop(L, 1);
      }
    }
    lua_pop(L, 1);
  }
}

template <template <class> class Registrar, class T>
void guardClassMethods(lua_State *L, Registrar<T> &) {
  guardClassMethods<T>(L);
}

// LuaBridge's class-method fallback otherwise shadows a same-name static API.
// Consult the static method table first; userdata keeps its instance methods.
template <template <class> class Registrar, class T>
void preferStaticClassFunctions(lua_State *, Registrar<T> &registration) {
  registration.addStaticIndexMetaMethod(&detail::staticClassFunction<T>);
}
} // namespace qtluau
#endif
