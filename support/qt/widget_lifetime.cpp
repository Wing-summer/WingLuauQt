// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/widget_wrappers.hpp"

namespace qtluau {
WidgetLifetime::WidgetLifetime(QWidget *value, bool isOwned)
    : widget(value), owned(isOwned) {}
WidgetLifetime::~WidgetLifetime() {
  QWidget *p = widget.data();
  if (owned && p && !p->parent()) {
    // QWidget destruction must happen on its affinity thread. deleteLater() is
    // thread-safe and prevents Lua-state teardown on a worker from deleting a
    // widget.
    if (QThread::currentThread() == p->thread()) {
      delete p;
    } else {
      p->deleteLater();
    }
  }
}
LayoutLifetime::LayoutLifetime(QLayout *value, bool isOwned)
    : layout(value), owned(isOwned) {}
LayoutLifetime::~LayoutLifetime() {
  QLayout *p = layout.data();
  if (owned && p && !p->parent()) {
    if (QThread::currentThread() == p->thread()) {
      delete p;
    } else {
      p->deleteLater();
    }
  }
}

QtWidgetRef::QtWidgetRef(QWidget *widget, bool owned)
    : lifetime_(std::make_shared<WidgetLifetime>(widget, owned)) {
  if (!widget) {
    throw std::invalid_argument("QWidget pointer must not be null");
  }
}
QWidget *QtWidgetRef::get() const {
  QWidget *p = lifetime_ ? lifetime_->widget.data() : nullptr;
  if (!p) {
    throw std::runtime_error("Qt widget has already been destroyed");
  }
  if (QThread::currentThread() != p->thread()) {
    throw std::runtime_error(
        "Qt widget access must run on the object's thread");
  }
  return p;
}

QtLayoutRef::QtLayoutRef() = default;
QtLayoutRef::QtLayoutRef(QLayout *layout, bool owned)
    : lifetime_(std::make_shared<LayoutLifetime>(layout, owned)) {
  if (!layout) {
    throw std::invalid_argument("QLayout pointer must not be null");
  }
}
QLayout *QtLayoutRef::get() const {
  QLayout *p = lifetime_ ? lifetime_->layout.data() : nullptr;
  if (!p) {
    throw std::runtime_error("Qt layout has already been destroyed");
  }
  if (QThread::currentThread() != p->thread()) {
    throw std::runtime_error(
        "Qt layout access must run on the object's thread");
  }
  return p;
}

} // namespace qtluau
