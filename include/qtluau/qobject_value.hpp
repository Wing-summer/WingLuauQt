// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#ifndef QTLUAU_INCLUDE_QTLUAU_QOBJECT_VALUE_HPP
#define QTLUAU_INCLUDE_QTLUAU_QOBJECT_VALUE_HPP
#include "qtluau/bindings.hpp"
#include <QObject>
#include <QPointer>
#include <QThread>
#include <memory>
namespace qtluau {
class QObjectRef {
public:
  explicit QObjectRef(QObject *object, bool owned = false, bool readOnly = false)
      : lifetime_(std::make_shared<Lifetime>(object, owned, readOnly)) {}
  QObject *get() const {
    auto *object = lifetime_->object.data();
    if (!object) {
      throw std::runtime_error("QObject has been deleted");
    }
    if (object->thread() != QThread::currentThread()) {
      throw std::runtime_error("QObject accessed from another thread");
    }
    return object;
  }
  void requireWritable() const {
    if (lifetime_->readOnly) { throw std::runtime_error("Qt object is read-only"); }
  }
  void releaseOwnership() { requireWritable(); lifetime_->owned = false; }
  void connect(const std::string &signal, luabridge::LuaRef callback);
  luabridge::LuaRef property(const std::string &name, lua_State *L) const;
  bool setProperty(const std::string &name, const luabridge::LuaRef &value);

private:
  struct Lifetime {
    QPointer<QObject> object;
    bool owned;
    bool readOnly;
    Lifetime(QObject *value, bool own, bool immutable) : object(value), owned(own), readOnly(immutable) {}
    ~Lifetime() {
      if (owned && object && !object->parent()) {
        if (object->thread() == QThread::currentThread()) {
          delete object.data();
        } else {
          object->deleteLater();
        }
      }
    }
  };
  std::shared_ptr<Lifetime> lifetime_;
};
} // namespace qtluau
#endif // QTLUAU_INCLUDE_QTLUAU_QOBJECT_VALUE_HPP
