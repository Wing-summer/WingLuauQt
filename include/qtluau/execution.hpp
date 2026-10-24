// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_EXECUTION_HPP
#define QTLUAU_INCLUDE_QTLUAU_EXECUTION_HPP

#include "qtluau/bindings.hpp"
#include <luacode.h>

namespace qtluau {
bool executeLuau(lua_State *L, QAnyStringView source,
                 QString *errorMessage = nullptr);
} // namespace qtluau

#endif // QTLUAU_INCLUDE_QTLUAU_EXECUTION_HPP
