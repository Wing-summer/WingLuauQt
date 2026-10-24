// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/qobject_value.hpp"
#include "qtluau/value_conversion.hpp"
#include "qtluau/widget_wrappers.hpp"
#include <QMetaProperty>

namespace qtluau {
luabridge::LuaRef QtWidgetRef::property(const std::string &name,
                                        lua_State *L) const {
  const QByteArray key(name.data(), static_cast<qsizetype>(name.size()));
  return variantToLua(L, get()->property(key.constData()));
}

bool QtWidgetRef::setProperty(const std::string &name,
                              const luabridge::LuaRef &value) {
  QWidget *widget = get();
  const QByteArray key(name.data(), static_cast<qsizetype>(name.size()));
  const int index = widget->metaObject()->indexOfProperty(key.constData());
  QVariant converted = variantFromLua(value);
  if (index >= 0) {
    const QMetaProperty property = widget->metaObject()->property(index);
    if (!property.isWritable()) {
      return false;
    }
    if (converted.metaType() != property.metaType() &&
        !converted.convert(property.metaType())) {
      return false;
    }
    return widget->setProperty(key.constData(), converted);
  }
  // Qt returns false for successful dynamic properties. Report whether the
  // requested value was actually stored (or removed for nil).
  widget->setProperty(key.constData(), converted);
  return widget->property(key.constData()) == converted;
}

luabridge::LuaRef QObjectRef::property(const std::string &name,
                                       lua_State *L) const {
  const QByteArray key(name.data(), static_cast<qsizetype>(name.size()));
  return variantToLua(L, get()->property(key.constData()));
}

bool QObjectRef::setProperty(const std::string &name,
                             const luabridge::LuaRef &value) {
  QObject *widget = get();
  const QByteArray key(name.data(), static_cast<qsizetype>(name.size()));
  const int index = widget->metaObject()->indexOfProperty(key.constData());
  QVariant converted = variantFromLua(value);
  if (index >= 0) {
    const QMetaProperty property = widget->metaObject()->property(index);
    if (!property.isWritable()) {
      return false;
    }
    if (converted.metaType() != property.metaType() &&
        !converted.convert(property.metaType())) {
      return false;
    }
    return widget->setProperty(key.constData(), converted);
  }
  // Qt returns false for successful dynamic properties. Report whether the
  // requested value was actually stored (or removed for nil).
  widget->setProperty(key.constData(), converted);
  return widget->property(key.constData()) == converted;
}

} // namespace qtluau
