// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#ifndef QTLUAU_INCLUDE_QTLUAU_UI_NOTIFICATIONS_HPP
#define QTLUAU_INCLUDE_QTLUAU_UI_NOTIFICATIONS_HPP
#include "qtluau/bindings.hpp"
namespace qtluau {
using UiWidgetCreated = std::function<void(QWidget *, const UiWidgetRequest &)>;
void setUiWidgetCreatedCallback(UiWidgetCreated callback);
namespace detail {
void notifyUiWidgetCreated(QWidget *widget, const UiWidgetRequest &request);
}
}
#endif
