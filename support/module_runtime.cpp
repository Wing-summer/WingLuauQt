// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#include "qtluau/module_values.hpp"
#include <string>
#include <unordered_set>

namespace qtluau {
namespace {
struct RegistrationRequest {
  QString name;
  ModuleRegistration registration;
};
void freezeModule(lua_State *L, int index, std::unordered_set<const void *> &visited) {
  index = lua_absindex(L, index);
  if (!lua_istable(L, index) || !visited.insert(lua_topointer(L, index)).second) { return; }
  lua_pushnil(L);
  while (lua_next(L, index)) {
    freezeModule(L, -1, visited);
    lua_pop(L, 1);
  }
  if (lua_getmetatable(L, index)) {
    freezeModule(L, -1, visited);
    lua_pop(L, 1);
  }
  lua_setreadonly(L, index, true);
}
int registerRequestedModule(lua_State *L) {
  auto *request = static_cast<RegistrationRequest *>(lua_touserdata(L, lua_upvalueindex(1)));
  request->registration(L, request->name);
  if (!pushModule(L, request->name)) {
    throw std::runtime_error("Generated module value is missing");
  }
  std::unordered_set<const void *> visited;
  freezeModule(L, -1, visited);
  return 1;
}
} // namespace

int loadRegisteredModule(lua_State *caller, QAnyStringView name,
                         ModuleRegistration registration) {
  lua_State *main = lua_mainthread(caller);
  lua_State *thread = lua_newthread(main);
  const int reference = lua_ref(main, -1);
  lua_pop(main, 1);
  RegistrationRequest request{name.toString(), registration};
  try {
    luaL_sandboxthread(thread);
    lua_pushvalue(thread, LUA_GLOBALSINDEX);
    lua_setglobal(thread, "_G");
    lua_pushlightuserdata(thread, &request);
    lua_pushcclosure(thread, registerRequestedModule, "registerModule", 1);
    if (lua_pcall(thread, 0, 1, 0) != LUA_OK) {
      const char *message = lua_tostring(thread, -1);
      throw std::runtime_error(message ? message : "Binding registration failed with a non-string error");
    }
    lua_xmove(thread, caller, 1);
  } catch (...) {
    lua_unref(main, reference);
    throw;
  }
  lua_unref(main, reference);
  return 1;
}
} // namespace qtluau
