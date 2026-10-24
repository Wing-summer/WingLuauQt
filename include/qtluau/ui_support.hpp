// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_UI_SUPPORT_HPP
#define QTLUAU_INCLUDE_QTLUAU_UI_SUPPORT_HPP
#include "qtluau/bindings.hpp"
#include "qtluau/widget_wrappers.hpp"
#include <QDir>
namespace qtluau::detail {
// Generated policy and callback-independent runtime support meet here.
bool isUiClassReserved(const QString &name);
UiWidgetResolver uiResolver();
UiWidgetFactory uiFactory(const QString &name);
QWidget *loadUiDocument(const QByteArray &bytes, const QDir &directory,
                        QString *error);
QtWidgetRef loadUiXml(const std::string &xml);
QtWidgetRef loadUiFile(const std::string &path, const QStringList &roots);
} // namespace qtluau::detail
#endif // QTLUAU_INCLUDE_QTLUAU_UI_SUPPORT_HPP
