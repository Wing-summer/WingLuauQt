// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_BINDINGS_HPP
#define QTLUAU_INCLUDE_QTLUAU_BINDINGS_HPP

// clang-format off
#include <lua.h>
#include <lualib.h>
#include <LuaBridge/LuaBridge.h>
// clang-format on


// IMPORTANT: Luau's C API headers must be included before LuaBridge3.

#include <QAnyStringView>
#include <QString>
#include <QStringList>

#include "qtluau/member_binding.hpp"
#include <functional>

class QWidget;
class QByteArray;

namespace qtluau {
// Push a non-owning (default) or owning wrapper for a host-created QWidget.
// This lets a host-owned QMainWindow/QDialog/custom window pass its existing
// content QWidget to Luau without exposing the window classes themselves.
void pushQtWidget(lua_State *L, QWidget *widget, bool takeOwnership = false);

// QUiLoader never exposes native plugin-path controls to Luau. Custom UI widget
// classes must be registered by trusted host code through this factory API.
using UiWidgetFactory = std::function<QWidget *(QWidget *parent)>;
void registerUiWidgetFactory(const QString &className, UiWidgetFactory factory);

// A host may replace/reject any UI class, including window roots and unknown
// classes.
struct UiWidgetRequest {
  QString className;
  QString objectName;
  QWidget *parent = nullptr;
  bool isRoot = false;
  bool isKnown = false;
  bool fromUi = true;
};
enum class UiWidgetAction { Default, Reject, Use };
struct UiWidgetResult {
  UiWidgetAction action = UiWidgetAction::Default;
  QWidget *widget = nullptr;
};
using UiWidgetResolver = std::function<UiWidgetResult(const UiWidgetRequest &)>;
void setUiWidgetResolver(UiWidgetResolver resolver);
using WidgetContentSetter = std::function<void(QWidget *, QWidget *)>;
using WidgetContentTaker = std::function<QWidget *(QWidget *)>;
void setWidgetContentMutators(WidgetContentSetter setter, WidgetContentTaker taker);
void replaceWidgetContentTarget(QWidget *widget, QWidget *content);
QWidget *takeWidgetContentTarget(QWidget *widget);
QWidget *windowContentTarget(QWidget *widget);
using WidgetContentResolver = std::function<QWidget *(QWidget *)>;
using UiWidgetFinalizer = std::function<void(QWidget *)>;
void setWidgetContentResolver(WidgetContentResolver resolver);
void setUiWidgetFinalizer(UiWidgetFinalizer finalizer);
QWidget *widgetContentTarget(QWidget *widget);
namespace detail {
bool isHostWindowClass(const QString &name);
QWidget *createHostWindow(const QString &name);
void finalizeUiWidget(QWidget *widget);
}

// Native host-side counterparts to the Lua UI loader. Returned widgets are
// newly allocated and owned by the caller until parented. File loading enforces
// qt.ui_tools.allowed_roots.
QWidget *loadUiWidgetFileNative(const QString &path,
                                const QStringList &allowedRoots,
                                QString *errorMessage = nullptr);
QWidget *loadUiWidgetXmlNative(const QByteArray &xml,
                               QString *errorMessage = nullptr);

// Release LuaRef objects held by Qt signal closures before lua_close(L). The
// integration executable calls this automatically; embedding hosts must do the
// same during shutdown.
void clearLuaCallbacks(lua_State *L);

} // namespace qtluau

#endif // QTLUAU_INCLUDE_QTLUAU_BINDINGS_HPP
