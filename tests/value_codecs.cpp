// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "static_registration.hpp"

#include "qtluau/value_conversion.hpp"
#include <QApplication>
#include <QColor>
#include <iostream>

namespace {
void require(bool result, const char *message) {
  if (!result) {
    throw std::runtime_error(message);
  }
}
} // namespace
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
    {
      const QMap<QString, QList<QColor>> colors = {
          {QStringLiteral("颜色"), {QColor(1, 2, 3), QColor(4, 5, 6)}}};
      auto table = qtluau::qtToLua(L, colors);
      require(qtluau::qtFromLua<QMap<QString, QList<QColor>>>(table) == colors,
              "Nested typed map/sequence/color roundtrip failed");
      const QList<QByteArray> binary = {QByteArray("a\0\xff", 3), QByteArray()};
      require(qtluau::qtFromLua<QList<QByteArray>>(
                  qtluau::qtToLua(L, binary)) == binary,
              "Binary container roundtrip failed");
      const QHash<QString, QList<int>> numbers = {
          {QStringLiteral("numbers"), {1, 2, 3}}};
      require(qtluau::qtFromLua<QHash<QString, QList<int>>>(
                  qtluau::qtToLua(L, numbers)) == numbers,
              "Typed hash roundtrip failed");
      auto invalid = luabridge::LuaRef::newTable(L);
      invalid[1] = 1.5;
      const int top = lua_gettop(L);
      bool rejected = false;
      try {
        qtluau::qtFromLua<QList<int>>(invalid);
      } catch (const std::invalid_argument &) {
        rejected = true;
      }
      require(rejected && lua_gettop(L) == top,
              "Fractional integer or stack imbalance");
      const QList<qlonglong> signedValues = {
          std::numeric_limits<qlonglong>::min(), 9007199254740993LL,
          std::numeric_limits<qlonglong>::max()};
      require(qtluau::qtFromLua<QList<qlonglong>>(
                  qtluau::qtToLua(L, signedValues)) == signedValues,
              "Signed 64-bit roundtrip failed");
      const QList<qulonglong> unsignedValues = {
          0, std::numeric_limits<qulonglong>::max()};
      require(qtluau::qtFromLua<QList<qulonglong>>(
                  qtluau::qtToLua(L, unsignedValues)) == unsignedValues,
              "Unsigned 64-bit roundtrip failed");
      require(lua_gettop(L) == top, "Integer conversion stack imbalance");
    }
  } catch (const std::exception &error) {
    std::cerr << error.what() << '\n';
    status = 1;
  }
  qtluau::clearLuaCallbacks(L);
  lua_close(L);
  return status;
}
