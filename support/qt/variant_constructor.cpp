// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/value_conversion.hpp"
#include "qtluau/widget_wrappers.hpp"

namespace qtluau {
bool VariantBox::isValid() const { return value.isValid(); }
bool VariantBox::isNull() const { return value.isNull(); }
std::string VariantBox::typeName() const {
  return value.typeName() ? value.typeName() : "invalid";
}
luabridge::LuaRef VariantBox::toValue(lua_State *L) const {
  return variantToLua(L, value);
}

namespace {
QVariant requestedVariant(const luabridge::LuaRef &value,
                          const std::string &type) {
  QVariant native = variantFromLua(value);
  if (type.empty()) {
    return native;
  }
  const QMetaType target = QMetaType::fromName(QByteArray::fromStdString(type));
  // Only explicitly supported value types can be requested. No QObject/raw
  // pointer metatypes, conversion callbacks, or arbitrary host metatypes.
  const QList<int> allowed = {
      QMetaType::Bool,         QMetaType::Int,         QMetaType::UInt,
      QMetaType::LongLong,     QMetaType::ULongLong,   QMetaType::Double,
      QMetaType::QString,      QMetaType::QByteArray,  QMetaType::QStringList,
      QMetaType::QVariantList, QMetaType::QVariantMap, QMetaType::QColor,
      QMetaType::QFont};
  if (!allowed.contains(target.id())) {
    throw std::invalid_argument("Unsupported explicit QVariant type");
  }
  if (target.id() == QMetaType::QByteArray && value.isString()) {
    const std::string bytes = value.unsafe_cast<std::string>();
    return QByteArray(bytes.data(), static_cast<qsizetype>(bytes.size()));
  }
  if (target.id() == QMetaType::QStringList) {
    return qtFromLua<QStringList>(value);
  }
  if (target.id() == QMetaType::QVariantList) {
    return qtFromLua<QVariantList>(value);
  }
  if (target.id() == QMetaType::QVariantMap) {
    return qtFromLua<QVariantMap>(value);
  }
  if (!native.convert(target)) {
    throw std::invalid_argument(
        "Cannot convert value to requested QVariant type");
  }
  return native;
}
} // namespace
int constructVariant(lua_State *L) {
  // Raise the Luau error after C++ temporaries have been destroyed.
  std::string error;
  try {
    if (lua_gettop(L) > 2) {
      throw std::invalid_argument("Too many constructor arguments");
    }
    auto input = lua_gettop(L) ? luabridge::LuaRef::fromStack(L, 1)
                               : luabridge::LuaRef(L);
    if (lua_gettop(L) == 2 && lua_type(L, 2) != LUA_TSTRING) {
      throw std::invalid_argument("QVariant type name must be a string");
    }
    VariantBox box{
        requestedVariant(input, lua_gettop(L) == 2 ? lua_tostring(L, 2) : "")};
    const auto result = luabridge::Stack<VariantBox>::push(L, box);
    if (!result) {
      throw std::invalid_argument(result.message());
    }
    return 1;
  } catch (const std::exception &exception) {
    error = exception.what();
  }
  lua_pushlstring(L, error.data(), error.size());
  // lua_error can longjmp, so release the owned string before raising.
  {
    std::string released;
    error.swap(released);
  }
  lua_error(L);
  return 0;
}

} // namespace qtluau
