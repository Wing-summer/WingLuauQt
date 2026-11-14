// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_INTEGER64_HPP
#define QTLUAU_INCLUDE_QTLUAU_INTEGER64_HPP

#include <cstdint>
#include <limits>

struct lua_State;

namespace qtluau {
inline constexpr std::int64_t MaxSafeInteger =
    (std::int64_t{1} << std::numeric_limits<double>::digits) - 1;
void registerInteger64(lua_State *L);
bool readInteger64(lua_State *L, int index, std::int64_t &value);
bool readUnsignedInteger64(lua_State *L, int index, std::uint64_t &value);
bool isInteger64(lua_State *L, int index);
bool isUnsignedInteger64(lua_State *L, int index);
void pushInteger64(lua_State *L, std::int64_t value);
void pushUnsignedInteger64(lua_State *L, std::uint64_t value);
} // namespace qtluau
#endif // QTLUAU_INCLUDE_QTLUAU_INTEGER64_HPP
