// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_VALUE_CONVERSION_HPP
#define QTLUAU_INCLUDE_QTLUAU_VALUE_CONVERSION_HPP
#include "qtluau/bindings.hpp"
#include "qtluau/qobject_value.hpp"
#include "qtluau/widget_wrappers.hpp"
#include <QFlags>
#include <QHash>
#include <QList>
#include <QMap>
#include <QVariant>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <type_traits>

namespace qtluau {
struct VariantBox {
  QVariant value;
  bool isValid() const;
  bool isNull() const;
  std::string typeName() const;
  luabridge::LuaRef toValue(lua_State *L) const;
};
QVariant variantFromLua(const luabridge::LuaRef &value);
luabridge::LuaRef variantToLua(lua_State *L, const QVariant &value);
void pushNullValue(lua_State *L);

template <class T, class Enable = void> struct LuaCodec {
  static T read(const luabridge::LuaRef &value) {
    auto result = value.template cast<T>();
    if (!result) {
      throw std::invalid_argument("Expected registered Qt value type");
    }
    return *result;
  }
  static luabridge::LuaRef write(lua_State *L, const T &value) {
    return luabridge::LuaRef(L, value);
  }
};
template <class T>
struct LuaCodec<T *, std::enable_if_t<std::is_base_of_v<QObject, T>>> {
  static T *read(const luabridge::LuaRef &value) {
    if (value.isNil()) {
      return nullptr;
    }
    QObject *object = nullptr;
    if (auto native = value.template cast<QObjectRef>()) {
      object = native->get();
    } else if (auto widget = value.template cast<QtWidgetRef>()) {
      object = widget->get();
    } else if (auto layout = value.template cast<QtLayoutRef>()) {
      object = layout->get();
    }
    auto *converted = qobject_cast<T *>(object);
    if (!converted) {
      throw std::invalid_argument("Incompatible QObject argument");
    }
    return converted;
  }
  static luabridge::LuaRef write(lua_State *L, T *value) {
    if (!value) {
      return luabridge::LuaRef(L);
    }
    if constexpr (std::is_base_of_v<QWidget, T>) {
      pushQtWidget(L, value, false);
      auto result = luabridge::LuaRef::fromStack(L, -1);
      lua_pop(L, 1);
      return result;
    } else if constexpr (std::is_base_of_v<QLayout, T>) {
      return luabridge::LuaRef(L, QtLayoutRef(value, false));
    } else {
      return luabridge::LuaRef(L, QObjectRef(value));
    }
  }
};
template <class T>
struct LuaCodec<T, std::enable_if_t<std::is_arithmetic_v<T>>> {
  static T read(const luabridge::LuaRef &value) {
    if constexpr (std::is_same_v<T, bool>) {
      if (!value.isBool()) {
        throw std::invalid_argument("Expected boolean container element");
      }
      return value.template unsafe_cast<bool>();
    } else {
#ifdef lua_isinteger64
      if constexpr (std::is_integral_v<T>) {
        value.push();
        const bool integer = lua_isinteger64(value.state(), -1);
        const qint64 number =
            integer ? lua_tointeger64(value.state(), -1, nullptr) : 0;
        lua_pop(value.state(), 1);
        if (integer) {
          if (static_cast<long double>(number) <
                  std::numeric_limits<T>::lowest() ||
              static_cast<long double>(number) >
                  std::numeric_limits<T>::max()) {
            throw std::invalid_argument("Integer is outside the target range");
          }
          return static_cast<T>(number);
        }
        if constexpr (std::is_unsigned_v<T>) {
          if (auto boxed = value.template cast<VariantBox>()) {
            if (boxed->value.metaType().id() != QMetaType::ULongLong ||
                boxed->value.toULongLong() > std::numeric_limits<T>::max()) {
              throw std::invalid_argument(
                  "Expected an unsigned integer variant in range");
            }
            return static_cast<T>(boxed->value.toULongLong());
          }
        }
      }
#endif
      if (!value.isNumber()) {
        throw std::invalid_argument("Expected numeric container element");
      }
      const double number = value.template unsafe_cast<double>();
      if (!std::isfinite(number)) {
        throw std::invalid_argument("Non-finite container element");
      }
      if constexpr (std::is_integral_v<T>) {
        if (std::floor(number) != number ||
            std::abs(number) > 9007199254740991.0 ||
            static_cast<long double>(number) <
                std::numeric_limits<T>::lowest() ||
            static_cast<long double>(number) > std::numeric_limits<T>::max()) {
          throw std::invalid_argument(
              "Container integer is out of range or not exact");
        }
      } else if (std::abs(static_cast<long double>(number)) >
                 std::numeric_limits<T>::max()) {
        throw std::invalid_argument("Container number is out of range");
      }
      return static_cast<T>(number);
    }
  }
  static luabridge::LuaRef write(lua_State *L, T value) {
    return variantToLua(L, QVariant::fromValue(value));
  }
};
template <> struct LuaCodec<QVariant> {
  static QVariant read(const luabridge::LuaRef &value) {
    return variantFromLua(value);
  }
  static luabridge::LuaRef write(lua_State *L, const QVariant &value) {
    return variantToLua(L, value);
  }
};
template <class T> struct LuaCodec<T, std::enable_if_t<std::is_enum_v<T>>> {
  static T read(const luabridge::LuaRef &value) {
    return static_cast<T>(LuaCodec<std::underlying_type_t<T>>::read(value));
  }
  static luabridge::LuaRef write(lua_State *L, T value) {
    return LuaCodec<std::underlying_type_t<T>>::write(
        L, static_cast<std::underlying_type_t<T>>(value));
  }
};
template <class Enum> struct LuaCodec<QFlags<Enum>> {
  using Flags = QFlags<Enum>;
  static Flags read(const luabridge::LuaRef &value) {
    return Flags::fromInt(LuaCodec<typename Flags::Int>::read(value));
  }
  static luabridge::LuaRef write(lua_State *L, Flags value) {
    return LuaCodec<typename Flags::Int>::write(L, value.toInt());
  }
};
template <> struct LuaCodec<QString> {
  static QString read(const luabridge::LuaRef &value);
  static luabridge::LuaRef write(lua_State *L, const QString &value);
};
template <> struct LuaCodec<QByteArray> {
  static QByteArray read(const luabridge::LuaRef &value);
  static luabridge::LuaRef write(lua_State *L, const QByteArray &value);
};
template <class T> struct LuaCodec<QList<T>> {
  static QList<T> read(const luabridge::LuaRef &value) {
    // Validate shape/cycles before walking typed elements. A list has dense,
    // one-based integer keys; a map or a sparse/mixed table is not a list.
    QVariant shape = variantFromLua(value);
    if (shape.metaType().id() != QMetaType::QVariantList) {
      throw std::invalid_argument("Expected dense sequence table");
    }
    QList<T> result;
    const qsizetype size = shape.toList().size();
    for (qsizetype i = 1; i <= size; ++i) {
      result.append(LuaCodec<T>::read(value[static_cast<int>(i)]));
    }
    return result;
  }
  static luabridge::LuaRef write(lua_State *L, const QList<T> &value) {
    auto result = luabridge::LuaRef::newTable(L);
    int index = 1;
    for (const T &entry : value) {
      result[index++] = LuaCodec<T>::write(L, entry);
    }
    return result;
  }
};
template <class T> struct LuaCodec<QMap<QString, T>> {
  static QMap<QString, T> read(const luabridge::LuaRef &value) {
    QVariant shape = variantFromLua(value);
    QMap<QString, T> result;
    if (shape.metaType().id() == QMetaType::QVariantList &&
        shape.toList().isEmpty()) {
      return result;
    }
    if (shape.metaType().id() != QMetaType::QVariantMap) {
      throw std::invalid_argument("Expected string-keyed map table");
    }
    for (const QString &key : shape.toMap().keys()) {
      const QByteArray utf8 = key.toUtf8();
      result.insert(
          key,
          LuaCodec<T>::read(value[std::string(utf8.constData(), utf8.size())]));
    }
    return result;
  }
  static luabridge::LuaRef write(lua_State *L, const QMap<QString, T> &value) {
    auto result = luabridge::LuaRef::newTable(L);
    for (auto it = value.begin(); it != value.end(); ++it) {
      const QByteArray key = it.key().toUtf8();
      result[std::string(key.constData(), key.size())] =
          LuaCodec<T>::write(L, it.value());
    }
    return result;
  }
};
template <class T> struct LuaCodec<QHash<QString, T>> {
  static QHash<QString, T> read(const luabridge::LuaRef &value) {
    const auto map = LuaCodec<QMap<QString, T>>::read(value);
    QHash<QString, T> result;
    for (auto it = map.begin(); it != map.end(); ++it) {
      result.insert(it.key(), it.value());
    }
    return result;
  }
  static luabridge::LuaRef write(lua_State *L, const QHash<QString, T> &value) {
    QMap<QString, T> sorted;
    for (auto it = value.begin(); it != value.end(); ++it) {
      sorted.insert(it.key(), it.value());
    }
    return LuaCodec<QMap<QString, T>>::write(L, sorted);
  }
};
template <class T> T qtFromLua(const luabridge::LuaRef &value) {
  return LuaCodec<T>::read(value);
}
template <class T> luabridge::LuaRef qtToLua(lua_State *L, const T &value) {
  return LuaCodec<T>::write(L, value);
}
} // namespace qtluau

// Distinct argument types let LuaBridge resolve equal-arity overloads before
// invoking them, while keeping all Qt conversion in the shared codecs.
namespace qtluau {
template <class T> struct QtArgument {
  T value;
};
} // namespace qtluau
namespace luabridge {
template <class T> struct Stack<qtluau::QtArgument<T>> {
  static TypeResult<qtluau::QtArgument<T>> get(lua_State *L, int index) {
    try {
      return qtluau::QtArgument<T>{
          qtluau::qtFromLua<T>(LuaRef::fromStack(L, index))};
    } catch (const std::exception &) {
      return makeErrorCode(ErrorCode::InvalidTypeCast);
    }
  }
  static bool isInstance(lua_State *L, int index) {
    return bool(get(L, index));
  }
  static Result push(lua_State *L, const qtluau::QtArgument<T> &value) {
    qtluau::qtToLua(L, value.value).push();
    return {};
  }
};
} // namespace luabridge

#endif // QTLUAU_INCLUDE_QTLUAU_VALUE_CONVERSION_HPP
