// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/widget_wrappers.hpp"
#include <QGlobalStatic>
#include <QHash>
#include <QMutex>
#include <QMutexLocker>

namespace qtluau {
namespace {
struct Lifetimes {
  QMutex mutex;
  QHash<QWidget *, std::weak_ptr<WidgetLifetime>> widgets;
  QHash<QLayout *, std::weak_ptr<LayoutLifetime>> layouts;
};
Q_GLOBAL_STATIC(Lifetimes, lifetimes)

template <class Native, class Lifetime>
std::shared_ptr<Lifetime> sharedLifetime(Native *object, bool owned,
                                        QHash<Native *, std::weak_ptr<Lifetime>> &entries) {
  if (!object) { throw std::invalid_argument("Native object must not be null"); }
  QMutexLocker lock(&lifetimes->mutex);
  const bool tracked = entries.contains(object);
  if (auto existing = entries.value(object).lock()) {
    existing->owned = existing->owned || owned;
    return existing;
  }
  auto result = std::make_shared<Lifetime>(object, owned);
  entries.insert(object, result);
  if (!tracked) { QObject::connect(object, &QObject::destroyed, object, [object, &entries]() {
    if (!lifetimes.isDestroyed()) {
      QMutexLocker lock(&lifetimes->mutex);
      entries.remove(object);
    }
  }); }
  return result;
}
} // namespace

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
    : lifetime_(sharedLifetime(widget, owned, lifetimes->widgets)) {
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
    : lifetime_(sharedLifetime(layout, owned, lifetimes->layouts)) {
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
