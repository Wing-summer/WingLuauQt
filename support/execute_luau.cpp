// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/execution.hpp"

#include <QByteArray>
#include <QString>
#include <cstdlib>

namespace qtluau {

bool executeLuau(lua_State *L, QAnyStringView source, QString *errorMessage) {
  if (!L) {
    if (errorMessage) {
      *errorMessage = QStringLiteral("lua_State is null");
    }
    return false;
  }
  const QByteArray code = source.toString().toUtf8();
  lua_CompileOptions options{};
  options.optimizationLevel = 1;
  options.debugLevel = 1;
  size_t bytecodeSize = 0;
  char *bytecode =
      luau_compile(code.constData(), static_cast<size_t>(code.size()), &options,
                   &bytecodeSize);
  if (!bytecode) {
    if (errorMessage) {
      *errorMessage = QStringLiteral("luau_compile returned null bytecode");
    }
    return false;
  }
  const int loadResult = luau_load(L, "=qtluau", bytecode, bytecodeSize, 0);
  std::free(bytecode);
  if (loadResult != 0) {
    size_t length = 0;
    const char *message = lua_tolstring(L, -1, &length);
    if (errorMessage) {
      *errorMessage =
          message ? QString::fromUtf8(message, static_cast<qsizetype>(length))
                  : QStringLiteral("Luau bytecode load failed");
    }
    lua_pop(L, 1);
    return false;
  }
  const int callResult = lua_pcall(L, 0, 0, 0);
  if (callResult != 0) {
    size_t length = 0;
    const char *message = lua_tolstring(L, -1, &length);
    if (errorMessage) {
      *errorMessage =
          message ? QString::fromUtf8(message, static_cast<qsizetype>(length))
                  : QStringLiteral("Luau execution failed");
    }
    lua_pop(L, 1);
    return false;
  }
  return true;
}

} // namespace qtluau
