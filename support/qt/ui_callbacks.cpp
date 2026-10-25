// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/ui_support.hpp"
#include "qtluau/ui_notifications.hpp"
#include "qtluau/window_menu.hpp"
#include <QHash>
#include <QMainWindow>
#include <QMutex>
#include <QMutexLocker>

namespace qtluau {
namespace {
QMutex g_factoryMutex;
QHash<QString, UiWidgetFactory> g_widgetFactories;
UiWidgetResolver g_widgetResolver;
WidgetContentResolver g_contentResolver;
WidgetContentSetter g_contentSetter;
WidgetContentTaker g_contentTaker;
UiWidgetFinalizer g_finalizer;
UiWidgetCreated g_created;
WindowMenuResolver g_menuResolver;
WindowMenuSetter g_menuSetter;
} // namespace
namespace detail {
void notifyUiWidgetCreated(QWidget *widget, const UiWidgetRequest &request) {
  UiWidgetCreated callback;
  { QMutexLocker locker(&g_factoryMutex); callback = g_created; }
  if (widget && callback) { callback(widget, request); }
}
QWidget *createHostWindow(const QString &name) {
  auto resolver = uiResolver();
  const auto result = resolver ? resolver({name, QString(), nullptr, true, true, false}) : UiWidgetResult{};
  if (result.action != UiWidgetAction::Use || !result.widget) {
    throw std::runtime_error("Host window factory is required");
  }
  return result.widget;
}
void finalizeUiWidget(QWidget *widget) {
  UiWidgetFinalizer finalizer;
  { QMutexLocker locker(&g_factoryMutex); finalizer = g_finalizer; }
  if (finalizer) { finalizer(widget); }
}
UiWidgetResolver uiResolver() {
  QMutexLocker locker(&g_factoryMutex);
  return g_widgetResolver;
}
UiWidgetFactory uiFactory(const QString &name) {
  QMutexLocker locker(&g_factoryMutex);
  return g_widgetFactories.value(name);
}
} // namespace detail
void setUiWidgetCreatedCallback(UiWidgetCreated callback) {
  QMutexLocker locker(&g_factoryMutex);
  g_created = std::move(callback);
}
void setUiWidgetResolver(UiWidgetResolver resolver) {
  QMutexLocker locker(&g_factoryMutex);
  g_widgetResolver = std::move(resolver);
}

void setWidgetContentResolver(WidgetContentResolver resolver) {
  QMutexLocker locker(&g_factoryMutex);
  g_contentResolver = std::move(resolver);
}
void setUiWidgetFinalizer(UiWidgetFinalizer finalizer) {
  QMutexLocker locker(&g_factoryMutex);
  g_finalizer = std::move(finalizer);
}
QWidget *windowContentTarget(QWidget *widget) {
  WidgetContentResolver resolver;
  { QMutexLocker locker(&g_factoryMutex); resolver = g_contentResolver; }
  auto *target = resolver ? resolver(widget) : widget;
  if (target == widget) {
    if (auto *window = qobject_cast<QMainWindow *>(widget)) { return window->centralWidget(); }
  }
  return target;
}

QWidget *widgetContentTarget(QWidget *widget) {
  WidgetContentResolver resolver;
  { QMutexLocker locker(&g_factoryMutex); resolver = g_contentResolver; }
  auto *content = resolver ? resolver(widget) : widget;
  if (!content) { throw std::runtime_error("Window has no content widget"); }
  return content;
}
void setWidgetContentMutators(WidgetContentSetter setter, WidgetContentTaker taker) {
  QMutexLocker locker(&g_factoryMutex);
  g_contentSetter = std::move(setter);
  g_contentTaker = std::move(taker);
}
void replaceWidgetContentTarget(QWidget *widget, QWidget *content) {
  WidgetContentSetter setter;
  { QMutexLocker locker(&g_factoryMutex); setter = g_contentSetter; }
  if (!setter) { throw std::runtime_error("Host content setter is required"); }
  setter(widget, content);
}
QWidget *takeWidgetContentTarget(QWidget *widget) {
  WidgetContentTaker taker;
  { QMutexLocker locker(&g_factoryMutex); taker = g_contentTaker; }
  if (!taker) { throw std::runtime_error("Host content taker is required"); }
  return taker(widget);
}

void setWindowMenuAccessors(WindowMenuResolver resolver, WindowMenuSetter setter) {
  QMutexLocker locker(&g_factoryMutex);
  g_menuResolver = std::move(resolver);
  g_menuSetter = std::move(setter);
}
QWidget *windowMenuTarget(QWidget *widget, bool create) {
  WindowMenuResolver resolver;
  { QMutexLocker locker(&g_factoryMutex); resolver = g_menuResolver; }
  if (!resolver) { throw std::runtime_error("Host menu resolver is required"); }
  return resolver(widget, create);
}
void replaceWindowMenuTarget(QWidget *widget, QWidget *menu) {
  WindowMenuSetter setter;
  { QMutexLocker locker(&g_factoryMutex); setter = g_menuSetter; }
  if (!setter) { throw std::runtime_error("Host menu setter is required"); }
  setter(widget, menu);
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
