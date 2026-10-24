// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#ifndef QTLUAU_INCLUDE_QTLUAU_QOBJECT_VALUE_HPP
#define QTLUAU_INCLUDE_QTLUAU_QOBJECT_VALUE_HPP
#include "qtluau/bindings.hpp"
#include <QObject>
#include <QPointer>
#include <QThread>
namespace qtluau {
class QObjectRef {
public:
  explicit QObjectRef(QObject *object) : object_(object) {}
  QObject *get() const {
    if (!object_) {
      throw std::runtime_error("QObject has been deleted");
    }
    if (object_->thread() != QThread::currentThread()) {
      throw std::runtime_error("QObject accessed from another thread");
    }
    return object_;
  }
  void connect(const std::string &signal, luabridge::LuaRef callback);
  luabridge::LuaRef property(const std::string &name, lua_State *L) const;
  bool setProperty(const std::string &name, const luabridge::LuaRef &value);

private:
  QPointer<QObject> object_;
};
} // namespace qtluau
#endif // QTLUAU_INCLUDE_QTLUAU_QOBJECT_VALUE_HPP
