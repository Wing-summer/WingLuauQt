// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_MODULE_CATALOG_HPP
#define QTLUAU_INCLUDE_QTLUAU_MODULE_CATALOG_HPP

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QStringList>

namespace qtluau {
inline QStringList publicModuleNames(const QString &root) {
  if (root.isEmpty()) {
    return {};
  }
  QFile catalog(QDir(root).filePath(QStringLiteral(".luau-modules.json")));
  if (!catalog.open(QIODevice::ReadOnly)) {
    return {};
  }
  const auto entries = QJsonDocument::fromJson(catalog.readAll()).array();
  QStringList modules;
  for (const auto &entry : entries) {
    const auto name = entry.toString();
    if (!name.isEmpty()) {
      modules.append(name);
    }
  }
  modules.removeDuplicates();
  modules.sort();
  return modules;
}
} // namespace qtluau

#endif // QTLUAU_INCLUDE_QTLUAU_MODULE_CATALOG_HPP
