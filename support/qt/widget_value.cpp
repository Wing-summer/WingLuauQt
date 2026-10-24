// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/bindings.hpp"
#include "qtluau/widget_wrappers.hpp"

namespace qtluau {
void pushQtWidget(lua_State *L, QWidget *widget, bool takeOwnership) {
  if (!L) {
    throw std::invalid_argument("pushQtWidget: lua_State is null");
  }
  if (!widget) {
    lua_pushnil(L);
    return;
  }
  const auto result = luabridge::Stack<QtWidgetRef>::push(
      L, QtWidgetRef(widget, takeOwnership));
  if (!result) {
    throw std::runtime_error(std::string("Unable to push QWidget wrapper: ") +
                             result.message());
  }
}

} // namespace qtluau
