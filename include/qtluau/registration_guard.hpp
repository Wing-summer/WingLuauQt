// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#ifndef QTLUAU_INCLUDE_QTLUAU_REGISTRATION_GUARD_HPP
#define QTLUAU_INCLUDE_QTLUAU_REGISTRATION_GUARD_HPP
#include "qtluau/bindings.hpp"
#include <stdexcept>

namespace qtluau {
class RegistrationGuard {
  lua_State *state_;
  const char *key_;
  bool active_ = false;

  void set(int state) {
    lua_getfield(state_, LUA_REGISTRYINDEX, "qtluau.registration.states");
    lua_pushinteger(state_, state);
    lua_setfield(state_, -2, key_);
    lua_pop(state_, 1);
  }

public:
  RegistrationGuard(lua_State *state, const char *key) : state_(state), key_(key) {
    if (!state_) { throw std::invalid_argument("Null registration state"); }
    lua_getfield(state_, LUA_REGISTRYINDEX, "qtluau.registration.states");
    if (lua_isnil(state_, -1)) {
      lua_pop(state_, 1);
      lua_newtable(state_);
      lua_pushvalue(state_, -1);
      lua_setfield(state_, LUA_REGISTRYINDEX, "qtluau.registration.states");
    }
    lua_getfield(state_, -1, key_);
    const int status = lua_tointeger(state_, -1);
    lua_pop(state_, 2);
    if (status == 2) { return; }
    if (status != 0) {
      throw std::runtime_error("Recursive or previously failed Qt registration");
    }
    set(1);
    active_ = true;
  }
  RegistrationGuard(const RegistrationGuard &) = delete;
  RegistrationGuard &operator=(const RegistrationGuard &) = delete;
  ~RegistrationGuard() { if (active_) { set(-1); } }
  explicit operator bool() const { return active_; }
  void complete() {
    set(2);
    active_ = false;
    lua_getfield(state_, LUA_REGISTRYINDEX, "qtluau.registration.counts");
    if (lua_isnil(state_, -1)) {
      lua_pop(state_, 1);
      lua_newtable(state_);
      lua_pushvalue(state_, -1);
      lua_setfield(state_, LUA_REGISTRYINDEX, "qtluau.registration.counts");
    }
    lua_getfield(state_, -1, key_);
    const int count = lua_tointeger(state_, -1);
    lua_pop(state_, 1);
    lua_pushinteger(state_, count + 1);
    lua_setfield(state_, -2, key_);
    lua_pop(state_, 1);
  }
};
} // namespace qtluau
#endif // QTLUAU_INCLUDE_QTLUAU_REGISTRATION_GUARD_HPP
