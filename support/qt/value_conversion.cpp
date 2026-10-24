// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/value_conversion.hpp"
#include "qtluau/widget_wrappers.hpp"
#include <QColor>
#include <QFont>
#include <cmath>
#include <limits>
#include <set>

namespace qtluau {
namespace {
char nullToken;
struct StackRestore {
  lua_State *L;
  int top;
  explicit StackRestore(lua_State *state) : L(state), top(lua_gettop(state)) {}
  ~StackRestore() { lua_settop(L, top); }
};
struct ReadContext {
  std::set<const void *> active;
  size_t nodes = 0;
};
QVariant read(lua_State *L, int index, ReadContext &context, int depth) {
  if (depth > 64 || ++context.nodes > 100000) {
    throw std::invalid_argument("Qt value exceeds conversion limits");
  }
  if (!lua_checkstack(L, 8)) {
    throw std::invalid_argument("Luau stack exhausted during Qt conversion");
  }
  index = lua_absindex(L, index);
  switch (lua_type(L, index)) {
  case LUA_TNIL:
    return {};
  case LUA_TBOOLEAN:
    return bool(lua_toboolean(L, index));
#ifdef lua_isinteger64
  case LUA_TINTEGER:
    return QVariant::fromValue<qlonglong>(lua_tointeger64(L, index, nullptr));
#endif
  case LUA_TNUMBER: {
    const double value = lua_tonumber(L, index);
    if (!std::isfinite(value)) {
      throw std::invalid_argument("Non-finite Qt numeric value");
    }
    return value;
  }
  case LUA_TSTRING: {
    size_t length;
    const char *text = lua_tolstring(L, index, &length);
    return QString::fromUtf8(text, static_cast<qsizetype>(length));
  }
  case LUA_TLIGHTUSERDATA:
    if (lua_touserdata(L, index) == &nullToken) {
      return QVariant::fromValue(nullptr);
    }
    break;
  case LUA_TTABLE: {
    const void *identity = lua_topointer(L, index);
    if (!context.active.insert(identity).second) {
      throw std::invalid_argument("Cyclic table cannot become a Qt container");
    }
    QVariantMap map;
    QMap<int, QVariant> sequence;
    lua_pushnil(L);
    while (lua_next(L, index)) {
      QVariant value = read(L, -1, context, depth + 1);
      if (lua_type(L, -2) == LUA_TSTRING) {
        size_t length;
        const char *key = lua_tolstring(L, -2, &length);
        map.insert(QString::fromUtf8(key, static_cast<qsizetype>(length)),
                   value);
      } else if (lua_type(L, -2) == LUA_TNUMBER) {
        double key = lua_tonumber(L, -2);
        if (key < 1 || key > std::numeric_limits<int>::max() ||
            std::floor(key) != key) {
          throw std::invalid_argument(
              "Sequence keys must be positive integers");
        }
        sequence.insert(static_cast<int>(key), value);
      } else {
        throw std::invalid_argument(
            "Qt containers require integer or string table keys");
      }
      lua_pop(L, 1);
    }
    context.active.erase(identity);
    if (!map.isEmpty() && !sequence.isEmpty()) {
      throw std::invalid_argument(
          "Mixed array/map table cannot become a Qt container");
    }
    if (!map.isEmpty()) {
      return map;
    }
    QVariantList list;
    int expected = 1;
    for (auto it = sequence.begin(); it != sequence.end(); ++it) {
      if (it.key() != expected++) {
        throw std::invalid_argument("Sparse table cannot become a Qt sequence");
      }
      list.append(it.value());
    }
    if (list.isEmpty() && lua_getmetatable(L, index)) {
      lua_getfield(L, -1, "__qtluau_object");
      const bool object = lua_toboolean(L, -1);
      lua_pop(L, 2);
      if (object) {
        return QVariantMap();
      }
    }
    return list;
  }
  case LUA_TUSERDATA: {
    auto value = luabridge::LuaRef::fromStack(L, index);
    if (auto box = value.cast<VariantBox>()) {
      return box->value;
    }
    if (auto text = value.cast<QtValueRef<QString>>()) {
      return text->value();
    }
    if (auto bytes = value.cast<QtValueRef<QByteArray>>()) {
      return bytes->value();
    }
    if (auto color = value.cast<QColor>()) {
      return QVariant::fromValue(*color);
    }
    if (auto font = value.cast<QFont>()) {
      return QVariant::fromValue(*font);
    }
    break;
  }
  }
  throw std::invalid_argument("Unsupported Luau value for QVariant");
}
void push(lua_State *L, const QVariant &value, int depth, size_t &nodes) {
  if (depth > 64 || ++nodes > 100000) {
    throw std::invalid_argument("Qt value exceeds conversion limits");
  }
  if (!lua_checkstack(L, 8)) {
    throw std::invalid_argument("Luau stack exhausted during Qt conversion");
  }
  switch (value.metaType().id()) {
  case QMetaType::UnknownType:
    lua_pushnil(L);
    return;
  case QMetaType::Nullptr:
    pushNullValue(L);
    return;
  case QMetaType::Bool:
    lua_pushboolean(L, value.toBool());
    return;
  case QMetaType::Int:
  case QMetaType::UInt:
  case QMetaType::LongLong:
  case QMetaType::ULongLong:
  case QMetaType::Long:
  case QMetaType::ULong:
  case QMetaType::Short:
  case QMetaType::UShort:
  case QMetaType::Char:
  case QMetaType::SChar:
  case QMetaType::UChar: {
    const long double number =
        value.metaType().id() == QMetaType::ULongLong ||
                value.metaType().id() == QMetaType::ULong
            ? static_cast<long double>(value.toULongLong())
            : static_cast<long double>(value.toLongLong());
#ifdef lua_isinteger64
    if (value.metaType().id() != QMetaType::LongLong &&
        value.metaType().id() != QMetaType::ULongLong &&
        value.metaType().id() != QMetaType::Long &&
        value.metaType().id() != QMetaType::ULong) {
      lua_pushnumber(L, static_cast<double>(number));
      return;
    }
    if (number > static_cast<long double>(std::numeric_limits<qint64>::max())) {
      auto result = luabridge::Stack<VariantBox>::push(L, VariantBox{value});
      if (!result) {
        throw std::invalid_argument(result.message());
      }
      return;
    }
    lua_pushinteger64(L, value.toLongLong());
    return;
#else
    if (std::abs(number) > 9007199254740991.0L) {
      throw std::invalid_argument("Qt integer cannot be represented exactly by "
                                  "a Luau number; keep it boxed");
    }
    lua_pushnumber(L, static_cast<double>(number));
    return;
#endif
  }
  case QMetaType::Float:
  case QMetaType::Double:
    if (!std::isfinite(value.toDouble())) {
      throw std::invalid_argument("Non-finite Qt numeric value");
    }
    lua_pushnumber(L, value.toDouble());
    return;
  case QMetaType::QString: {
    const QByteArray bytes = value.toString().toUtf8();
    lua_pushlstring(L, bytes.constData(), bytes.size());
    return;
  }
  case QMetaType::QByteArray: {
    const QByteArray bytes = value.toByteArray();
    lua_pushlstring(L, bytes.constData(), bytes.size());
    return;
  }
  case QMetaType::QStringList: {
    const auto list = value.toStringList();
    lua_createtable(L, list.size(), 0);
    int index = 1;
    for (const auto &entry : list) {
      push(L, entry, depth + 1, nodes);
      lua_rawseti(L, -2, index++);
    }
    return;
  }
  case QMetaType::QVariantList: {
    const auto list = value.toList();
    lua_createtable(L, list.size(), 0);
    int index = 1;
    for (const auto &entry : list) {
      if (!entry.isValid()) {
        pushNullValue(L);
      } else {
        push(L, entry, depth + 1, nodes);
      }
      lua_rawseti(L, -2, index++);
    }
    return;
  }
  case QMetaType::QVariantMap:
  case QMetaType::QVariantHash: {
    QVariantMap map;
    if (value.metaType().id() == QMetaType::QVariantHash) {
      const auto hash = value.toHash();
      for (auto it = hash.begin(); it != hash.end(); ++it) {
        map.insert(it.key(), it.value());
      }
    } else {
      map = value.toMap();
    }
    lua_createtable(L, 0, map.size());
    lua_newtable(L);
    lua_pushboolean(L, true);
    lua_setfield(L, -2, "__qtluau_object");
    lua_setmetatable(L, -2);
    for (auto it = map.begin(); it != map.end(); ++it) {
      const QByteArray key = it.key().toUtf8();
      lua_pushlstring(L, key.constData(), key.size());
      if (!it.value().isValid()) {
        pushNullValue(L);
      } else {
        push(L, it.value(), depth + 1, nodes);
      }
      lua_rawset(L, -3);
    }
    return;
  }
  case QMetaType::QColor: {
    auto result = luabridge::Stack<QColor>::push(L, value.value<QColor>());
    if (!result) {
      throw std::invalid_argument(result.message());
    }
    return;
  }
  case QMetaType::QFont: {
    auto result = luabridge::Stack<QFont>::push(L, value.value<QFont>());
    if (!result) {
      throw std::invalid_argument(result.message());
    }
    return;
  }
  default:
    throw std::invalid_argument(
        std::string("Unregistered QVariant metatype: ") + value.typeName());
  }
}
} // namespace
void pushNullValue(lua_State *L) { lua_pushlightuserdata(L, &nullToken); }
QVariant variantFromLua(const luabridge::LuaRef &value) {
  lua_State *L = value.state();
  StackRestore restore(L);
  value.push();
  ReadContext context;
  return read(L, -1, context, 0);
}
luabridge::LuaRef variantToLua(lua_State *L, const QVariant &value) {
  StackRestore restore(L);
  size_t nodes = 0;
  push(L, value, 0, nodes);
  return luabridge::LuaRef::fromStack(L, -1);
}
QByteArray LuaCodec<QByteArray>::read(const luabridge::LuaRef &value) {
  if (value.isString()) {
    const auto bytes = value.unsafe_cast<std::string>();
    return QByteArray(bytes.data(), static_cast<qsizetype>(bytes.size()));
  }
  if (auto bytes = value.cast<QtValueRef<QByteArray>>()) {
    return bytes->value();
  }
  throw std::invalid_argument("Expected binary string element");
}
luabridge::LuaRef LuaCodec<QByteArray>::write(lua_State *L,
                                              const QByteArray &value) {
  return luabridge::LuaRef(L, std::string(value.constData(), value.size()));
}
QString LuaCodec<QString>::read(const luabridge::LuaRef &value) {
  if (value.isString()) {
    return toQString(value.unsafe_cast<std::string>());
  }
  if (auto text = value.cast<QtValueRef<QString>>()) {
    return text->value();
  }
  throw std::invalid_argument("Expected string element");
}
luabridge::LuaRef LuaCodec<QString>::write(lua_State *L, const QString &value) {
  return luabridge::LuaRef(L, toUtf8String(value));
}
} // namespace qtluau
