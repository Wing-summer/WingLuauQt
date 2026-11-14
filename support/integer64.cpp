// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/integer64.hpp"

#include <cmath>
#include <limits>
#include <new>

#include <lua.h>
#include <lualib.h>

namespace qtluau {
namespace {
constexpr unsigned IntegerBits = std::numeric_limits<std::uint64_t>::digits;
constexpr unsigned HalfBits = std::numeric_limits<std::uint32_t>::digits;
constexpr std::uint64_t SignBit = std::uint64_t(1) << (IntegerBits - 1);
char signedMetatable;
char unsignedMetatable;
char operationCache;

struct Integer64 {
  std::uint64_t bits;
  bool isUnsigned;
};

enum class Operation {
  Add,
  Subtract,
  Multiply,
  Divide,
  Modulo,
  Negate,
  Equal,
  Less,
  LessEqual,
  ToString,
  ToHex,
  ToNumber,
  High,
  Low,
  And,
  Or,
  Xor,
  Not,
  LeftShift,
  RightShift,
  ArithmeticShift
};

std::int64_t signedBits(std::uint64_t bits) {
  return bits < SignBit ? static_cast<std::int64_t>(bits)
                        : -1 - static_cast<std::int64_t>(~bits);
}

void pushMetatable(lua_State *L, bool isUnsigned) {
  lua_pushlightuserdata(L, isUnsigned ? &unsignedMetatable : &signedMetatable);
  lua_rawget(L, LUA_REGISTRYINDEX);
}

const Integer64 *integer(lua_State *L, int index) {
  if (lua_type(L, index) != LUA_TUSERDATA || !lua_getmetatable(L, index)) {
    return nullptr;
  }
  pushMetatable(L, false);
  bool own = lua_rawequal(L, -1, -2);
  lua_pop(L, 1);
  if (!own) {
    pushMetatable(L, true);
    own = lua_rawequal(L, -1, -2);
    lua_pop(L, 1);
  }
  lua_pop(L, 1);
  return own ? static_cast<const Integer64 *>(lua_touserdata(L, index))
             : nullptr;
}

void push(lua_State *L, std::uint64_t bits, bool isUnsigned) {
  new (lua_newuserdata(L, sizeof(Integer64))) Integer64{bits, isUnsigned};
  pushMetatable(L, isUnsigned);
  lua_setmetatable(L, -2);
}

bool negative(const Integer64 &value) {
  return !value.isUnsigned && (value.bits & SignBit) != 0;
}

Integer64 operand(lua_State *L, int index) {
  if (const auto *value = integer(L, index)) {
    return *value;
  }
  if (lua_type(L, index) == LUA_TNUMBER) {
    const double value = lua_tonumber(L, index);
    if (std::isfinite(value) && std::trunc(value) == value &&
        std::abs(value) <= static_cast<double>(MaxSafeInteger)) {
      return {static_cast<std::uint64_t>(static_cast<std::int64_t>(value)),
              false};
    }
  }
  luaL_error(L, "%s", "Expected int64, uint64 or a safe integral number");
}

std::uint64_t inDomain(lua_State *L, const Integer64 &value, bool isUnsigned) {
  if ((isUnsigned && negative(value)) ||
      (!isUnsigned && value.isUnsigned && value.bits >= SignBit)) {
    luaL_error(L, "%s", "Integer is outside the target 64-bit range");
  }
  return value.bits;
}

std::uint64_t parse(lua_State *L, int index, bool isUnsigned) {
  size_t length = 0;
  const char *text = lua_tolstring(L, index, &length);
  size_t position = 0;
  bool minus = false;
  if (position < length && (text[position] == '-' || text[position] == '+')) {
    minus = text[position++] == '-';
  }
  if (minus && isUnsigned) {
    luaL_error(L, "%s", "uint64 cannot be negative");
  }
  unsigned base = 10;
  if (position + 1 < length && text[position] == '0') {
    const char prefix = text[position + 1];
    if (prefix == 'x' || prefix == 'X' || prefix == 'b' || prefix == 'B') {
      base = prefix == 'x' || prefix == 'X' ? 16 : 2;
      position += 2;
    }
  }
  if (position == length) {
    luaL_error(L, "%s", "Expected an integer string with digits");
  }
  const std::uint64_t limit = isUnsigned
                                  ? std::numeric_limits<std::uint64_t>::max()
                              : minus ? SignBit
                                      : SignBit - 1;
  std::uint64_t result = 0;
  for (; position < length; ++position) {
    const char ch = text[position];
    const unsigned digit = ch >= '0' && ch <= '9'   ? unsigned(ch - '0')
                           : ch >= 'a' && ch <= 'f' ? unsigned(ch - 'a' + 10)
                           : ch >= 'A' && ch <= 'F' ? unsigned(ch - 'A' + 10)
                                                    : 16;
    if (digit >= base || result > (limit - digit) / base) {
      luaL_error(L, "%s", "Invalid or out-of-range 64-bit integer string");
    }
    result = result * base + digit;
  }
  return minus ? std::uint64_t(0) - result : result;
}

int construct(lua_State *L) {
  const bool isUnsigned = lua_toboolean(L, lua_upvalueindex(1));
  if (lua_gettop(L) != 1) {
    luaL_error(L, "%s",
               "int64/uint64 expects one string, number or integer value");
  }
  const std::uint64_t bits = lua_type(L, 1) == LUA_TSTRING
                                 ? parse(L, 1, isUnsigned)
                                 : inDomain(L, operand(L, 1), isUnsigned);
  push(L, bits, isUnsigned);
  return 1;
}

void pushText(lua_State *L, std::uint64_t bits, bool minus, unsigned base) {
  char text[IntegerBits + 1];
  size_t position = sizeof(text);
  do {
    const auto digit = unsigned(bits % base);
    text[--position] = "0123456789abcdef"[digit];
    bits /= base;
  } while (bits != 0);
  if (minus) {
    text[--position] = '-';
  }
  lua_pushlstring(L, text + position, sizeof(text) - position);
}

bool less(const Integer64 &left, const Integer64 &right) {
  const bool leftNegative = negative(left);
  if (leftNegative != negative(right)) {
    return leftNegative;
  }
  return left.bits < right.bits;
}

int dispatch(lua_State *L) {
  const auto operation =
      static_cast<Operation>(lua_tointeger(L, lua_upvalueindex(1)));
  const auto left = operand(L, 1);
  const bool isUnsigned =
      integer(L, 1) ? left.isUnsigned : operand(L, 2).isUnsigned;
  if (operation == Operation::Equal || operation == Operation::Less ||
      operation == Operation::LessEqual) {
    const auto right = operand(L, 2);
    const bool equal =
        negative(left) == negative(right) && left.bits == right.bits;
    lua_pushboolean(L, operation == Operation::Equal  ? equal
                       : operation == Operation::Less ? less(left, right)
                                                      : !less(right, left));
    return 1;
  }
  const std::uint64_t a = inDomain(L, left, isUnsigned);
  if (operation == Operation::ToString || operation == Operation::ToHex) {
    const bool minus = operation == Operation::ToString && negative(left);
    pushText(L, minus ? std::uint64_t(0) - a : a, minus,
             operation == Operation::ToHex ? 16 : 10);
    return 1;
  }
  if (operation == Operation::ToNumber) {
    const std::uint64_t magnitude = negative(left) ? std::uint64_t(0) - a : a;
    if (magnitude > MaxSafeInteger) {
      luaL_error(L, "%s", "Integer exceeds Luau's safe number range");
    }
    lua_pushnumber(L, isUnsigned ? static_cast<double>(a)
                                 : static_cast<double>(signedBits(a)));
    return 1;
  }
  if (operation == Operation::High || operation == Operation::Low) {
    lua_pushnumber(L, static_cast<double>(
                          operation == Operation::High
                              ? a >> HalfBits
                              : a & std::numeric_limits<std::uint32_t>::max()));
    return 1;
  }
  std::uint64_t result = 0;
  if (operation == Operation::Negate) {
    if ((isUnsigned && a != 0) || (!isUnsigned && a == SignBit)) {
      luaL_error(L, "%s", "64-bit integer overflow");
    }
    result = std::uint64_t(0) - a;
  } else if (operation == Operation::Not) {
    result = ~a;
  } else if (operation == Operation::LeftShift ||
             operation == Operation::RightShift ||
             operation == Operation::ArithmeticShift) {
    const auto shiftValue = operand(L, 2);
    if (negative(shiftValue) || shiftValue.bits > IntegerBits) {
      luaL_error(L, "%s", "Shift count must be between 0 and 64");
    }
    const auto shift = unsigned(shiftValue.bits);
    if (shift == 0) {
      result = a;
    } else if (shift == IntegerBits) {
      result = operation == Operation::ArithmeticShift && (a & SignBit)
                   ? std::numeric_limits<std::uint64_t>::max()
                   : 0;
    } else if (operation == Operation::LeftShift) {
      result = a << shift;
    } else {
      result = a >> shift;
      if (operation == Operation::ArithmeticShift && (a & SignBit)) {
        result |= std::numeric_limits<std::uint64_t>::max()
                  << (IntegerBits - shift);
      }
    }
  } else {
    const std::uint64_t b = inDomain(L, operand(L, 2), isUnsigned);
    const std::int64_t sa = signedBits(a);
    const std::int64_t sb = signedBits(b);
    const std::int64_t minimum = std::numeric_limits<std::int64_t>::min();
    const std::int64_t maximum = std::numeric_limits<std::int64_t>::max();
    switch (operation) {
    case Operation::Add:
      if (isUnsigned ? a > std::numeric_limits<std::uint64_t>::max() - b
                     : (sb > 0 && sa > maximum - sb) ||
                           (sb < 0 && sa < minimum - sb)) {
        luaL_error(L, "%s", "64-bit integer overflow");
      }
      result = a + b;
      break;
    case Operation::Subtract:
      if (isUnsigned ? a < b
                     : (sb < 0 && sa > maximum + sb) ||
                           (sb > 0 && sa < minimum + sb)) {
        luaL_error(L, "%s", "64-bit integer overflow");
      }
      result = a - b;
      break;
    case Operation::Multiply: {
      const bool minus = !isUnsigned && ((sa < 0) != (sb < 0));
      const std::uint64_t ma = !isUnsigned && sa < 0 ? std::uint64_t(0) - a : a;
      const std::uint64_t mb = !isUnsigned && sb < 0 ? std::uint64_t(0) - b : b;
      const std::uint64_t limit =
          isUnsigned ? std::numeric_limits<std::uint64_t>::max()
          : minus    ? SignBit
                     : SignBit - 1;
      if (mb != 0 && ma > limit / mb) {
        luaL_error(L, "%s", "64-bit integer overflow");
      }
      result = ma * mb;
      if (minus) {
        result = std::uint64_t(0) - result;
      }
      break;
    }
    case Operation::Divide:
    case Operation::Modulo:
      if (b == 0) {
        luaL_error(L, "%s", "64-bit integer division by zero");
      }
      if (isUnsigned) {
        result = operation == Operation::Divide ? a / b : a % b;
      } else if (sa == minimum && sb == -1) {
        if (operation == Operation::Divide) {
          luaL_error(L, "%s", "64-bit integer overflow");
        }
        result = 0;
      } else {
        std::int64_t quotient = sa / sb;
        std::int64_t remainder = sa % sb;
        if (remainder != 0 && ((remainder < 0) != (sb < 0))) {
          --quotient;
          remainder += sb;
        }
        result = static_cast<std::uint64_t>(
            operation == Operation::Divide ? quotient : remainder);
      }
      break;
    case Operation::And:
      result = a & b;
      break;
    case Operation::Or:
      result = a | b;
      break;
    case Operation::Xor:
      result = a ^ b;
      break;
    default:
      luaL_error(L, "%s", "Invalid 64-bit integer operation");
    }
  }
  push(L, result, isUnsigned);
  return 1;
}

void addOperation(lua_State *L, const char *name, Operation operation) {
  lua_pushlightuserdata(L, &operationCache);
  lua_rawget(L, LUA_REGISTRYINDEX);
  lua_rawgeti(L, -1, static_cast<int>(operation));
  if (lua_isnil(L, -1)) {
    lua_pop(L, 1);
    lua_pushinteger(L, static_cast<int>(operation));
    lua_pushcclosure(L, dispatch, name, 1);
    lua_pushvalue(L, -1);
    lua_rawseti(L, -3, static_cast<int>(operation));
  }
  lua_remove(L, -2);
  lua_setfield(L, -2, name);
}

void registerType(lua_State *L, bool isUnsigned) {
  pushMetatable(L, isUnsigned);
  if (!lua_isnil(L, -1)) {
    lua_pop(L, 1);
    return;
  }
  lua_pop(L, 1);
  lua_newtable(L);
  lua_pushlightuserdata(L, isUnsigned ? &unsignedMetatable : &signedMetatable);
  lua_pushvalue(L, -2);
  lua_rawset(L, LUA_REGISTRYINDEX);
  lua_pushvalue(L, -1);
  lua_setfield(L, -2, "__index");
  lua_pushstring(L, isUnsigned ? "uint64" : "int64");
  lua_setfield(L, -2, "__type");
  lua_pushstring(L, "protected 64-bit integer");
  lua_setfield(L, -2, "__metatable");
  const struct {
    const char *name;
    Operation operation;
  } methods[] = {{"__add", Operation::Add},
                 {"__sub", Operation::Subtract},
                 {"__mul", Operation::Multiply},
                 {"__div", Operation::Divide},
                 {"__idiv", Operation::Divide},
                 {"__mod", Operation::Modulo},
                 {"__unm", Operation::Negate},
                 {"__eq", Operation::Equal},
                 {"__lt", Operation::Less},
                 {"__le", Operation::LessEqual},
                 {"__tostring", Operation::ToString},
                 {"to_string", Operation::ToString},
                 {"to_hex", Operation::ToHex},
                 {"to_number", Operation::ToNumber},
                 {"high", Operation::High},
                 {"low", Operation::Low},
                 {"band", Operation::And},
                 {"bor", Operation::Or},
                 {"bxor", Operation::Xor},
                 {"bnot", Operation::Not},
                 {"lshift", Operation::LeftShift},
                 {"rshift", Operation::RightShift},
                 {"arshift", Operation::ArithmeticShift}};
  for (const auto &method : methods) {
    addOperation(L, method.name, method.operation);
  }
  lua_setreadonly(L, -1, true);
  lua_pop(L, 1);
  lua_pushboolean(L, isUnsigned);
  lua_pushcclosure(L, construct, isUnsigned ? "uint64" : "int64", 1);
  lua_setglobal(L, isUnsigned ? "uint64" : "int64");
}
} // namespace

void registerInteger64(lua_State *L) {
  lua_pushlightuserdata(L, &operationCache);
  lua_rawget(L, LUA_REGISTRYINDEX);
  if (lua_isnil(L, -1)) {
    lua_pop(L, 1);
    lua_newtable(L);
    lua_pushlightuserdata(L, &operationCache);
    lua_pushvalue(L, -2);
    lua_rawset(L, LUA_REGISTRYINDEX);
  }
  lua_pop(L, 1);
  registerType(L, false);
  registerType(L, true);
}

bool readInteger64(lua_State *L, int index, std::int64_t &value) {
  const auto *entry = integer(L, index);
  if (!entry || (entry->isUnsigned && entry->bits >= SignBit)) {
    return false;
  }
  value = signedBits(entry->bits);
  return true;
}

bool readUnsignedInteger64(lua_State *L, int index, std::uint64_t &value) {
  const auto *entry = integer(L, index);
  if (!entry || negative(*entry)) {
    return false;
  }
  value = entry->bits;
  return true;
}

bool isInteger64(lua_State *L, int index) {
  return integer(L, index) != nullptr;
}

bool isUnsignedInteger64(lua_State *L, int index) {
  const auto *entry = integer(L, index);
  return entry && entry->isUnsigned;
}

void pushInteger64(lua_State *L, std::int64_t value) {
  push(L, static_cast<std::uint64_t>(value), false);
}

void pushUnsignedInteger64(lua_State *L, std::uint64_t value) {
  push(L, value, true);
}
} // namespace qtluau
