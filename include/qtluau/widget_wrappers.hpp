// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_WIDGET_WRAPPERS_HPP
#define QTLUAU_INCLUDE_QTLUAU_WIDGET_WRAPPERS_HPP
#include "qtluau/value_ref.hpp"
#include <QApplication>
#include <QLayout>
#include <QPointer>
#include <QThread>
#include <QWidget>
#include <memory>
#include <stdexcept>
#include <type_traits>
#include <utility>
struct lua_State;
namespace luabridge {
class LuaRef;
}
namespace qtluau {
struct WidgetLifetime {
  explicit WidgetLifetime(QWidget *value, bool owned = true);
  ~WidgetLifetime();
  QPointer<QWidget> widget;
  bool owned = true;
};

struct LayoutLifetime {
  explicit LayoutLifetime(QLayout *value, bool owned = true);
  ~LayoutLifetime();
  QPointer<QLayout> layout;
  bool owned = true;
};

namespace detail {
bool isHostWindowClass(const QString &name);
QWidget *createHostWindow(const QString &name);
template <class T, class... Args> T *makeQtWidget(Args &&...args) {
  auto *app = qobject_cast<QApplication *>(QCoreApplication::instance());
  if (!app || QThread::currentThread() != app->thread()) {
    throw std::runtime_error(
        "Qt GUI objects require a host QApplication and its GUI thread");
  }
  if constexpr (std::is_base_of_v<QWidget, T> && sizeof...(Args) == 0) {
    if (isHostWindowClass(QString::fromLatin1(T::staticMetaObject.className()))) {
      auto *widget = createHostWindow(QString::fromLatin1(T::staticMetaObject.className()));
      auto *typed = qobject_cast<T *>(widget);
      if (!typed) { delete widget; throw std::runtime_error("Incompatible host window factory"); }
      return typed;
    }
  }
  if constexpr (std::is_constructible_v<T, Args...>) {
    return new T(std::forward<Args>(args)...);
  } else {
    throw std::runtime_error(
        "The native class has no matching public constructor");
  }
}
} // namespace detail
class QtWidgetRef {
public:
  QtWidgetRef() : QtWidgetRef(detail::makeQtWidget<QWidget>()) {}
  explicit QtWidgetRef(QWidget *widget, bool owned = true);
  QWidget *get() const;
  void connect(const std::string &signal, luabridge::LuaRef callback);
  luabridge::LuaRef property(const std::string &name, lua_State *L) const;
  bool setProperty(const std::string &name, const luabridge::LuaRef &value);

protected:
  std::shared_ptr<WidgetLifetime> lifetime_;
};
class QtLayoutRef {
public:
  QtLayoutRef();
  explicit QtLayoutRef(QLayout *layout, bool owned = true);
  QLayout *get() const;

protected:
  std::shared_ptr<LayoutLifetime> lifetime_;
};
// Native methods and child lookup registrations are generated from the SDK.
template <class Native, class Base> class QtTypedRef : public Base {
public:
  QtTypedRef() : Base(detail::makeQtWidget<Native>()) {}
  explicit QtTypedRef(const std::string &text)
      : Base(detail::makeQtWidget<Native>(toQString(text))) {}
  explicit QtTypedRef(const QtValueRef<QString> &text)
      : Base(detail::makeQtWidget<Native>(text.value())) {}
  explicit QtTypedRef(Native *object, bool owned = false)
      : Base(object, owned) {}
};
template <class Native>
using QtTypedWidgetRef = QtTypedRef<Native, QtWidgetRef>;
template <class Native>
using QtTypedLayoutRef = QtTypedRef<Native, QtLayoutRef>;
} // namespace qtluau
#endif
