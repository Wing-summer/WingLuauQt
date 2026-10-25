// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#ifndef QTLUAU_INCLUDE_QTLUAU_WINDOW_MENU_HPP
#define QTLUAU_INCLUDE_QTLUAU_WINDOW_MENU_HPP
#include "qtluau/bindings.hpp"
namespace qtluau {
using WindowMenuResolver = std::function<QWidget *(QWidget *, bool)>;
using WindowMenuSetter = std::function<void(QWidget *, QWidget *)>;
void setWindowMenuAccessors(WindowMenuResolver resolver, WindowMenuSetter setter);
QWidget *windowMenuTarget(QWidget *widget, bool create);
void replaceWindowMenuTarget(QWidget *widget, QWidget *menu);
}
#endif
