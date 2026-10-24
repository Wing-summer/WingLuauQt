// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_CALLBACK_HPP
#define QTLUAU_INCLUDE_QTLUAU_CALLBACK_HPP
#include "qtluau/bindings.hpp"
#include <QObject>
#include <functional>
namespace qtluau {
void connectLuaSignal(QObject *sender, QAnyStringView signal,
                      luabridge::LuaRef callback);
std::function<void()> makeLuaCallback(luabridge::LuaRef callback);
} // namespace qtluau
#endif // QTLUAU_INCLUDE_QTLUAU_CALLBACK_HPP
