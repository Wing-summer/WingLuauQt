// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/ui_support.hpp"
#include <QHash>
#include <QMutex>
#include <QMutexLocker>

namespace qtluau {
namespace {
QMutex g_factoryMutex;
QHash<QString, UiWidgetFactory> g_widgetFactories;
UiWidgetResolver g_widgetResolver;
} // namespace
namespace detail {
UiWidgetResolver uiResolver() {
  QMutexLocker locker(&g_factoryMutex);
  return g_widgetResolver;
}
UiWidgetFactory uiFactory(const QString &name) {
  QMutexLocker locker(&g_factoryMutex);
  return g_widgetFactories.value(name);
}
} // namespace detail
void setUiWidgetResolver(UiWidgetResolver resolver) {
  QMutexLocker locker(&g_factoryMutex);
  g_widgetResolver = std::move(resolver);
}

void registerUiWidgetFactory(const QString &className,
                             UiWidgetFactory factory) {
  if (className.trimmed().isEmpty() || !factory) {
    throw std::invalid_argument(
        "UI widget factory requires a class name and a callable factory");
  }
  if (detail::isUiClassReserved(className)) {
    throw std::invalid_argument(
        "Cannot override a built-in or excluded Qt UI class name");
  }
  QMutexLocker locker(&g_factoryMutex);
  g_widgetFactories.insert(className, std::move(factory));
}

} // namespace qtluau
