// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/value_ref.hpp"
#include <stdexcept>
#include <type_traits>

namespace qtluau {
std::string toUtf8String(QAnyStringView value) {
  return value.visit([](auto view) -> std::string {
    if constexpr (std::is_same_v<decltype(view), QUtf8StringView>) {
      return std::string(view.data(), static_cast<size_t>(view.size()));
    } else {
      const QByteArray bytes = QAnyStringView(view).toString().toUtf8();
      return std::string(bytes.constData(), static_cast<size_t>(bytes.size()));
    }
  });
}

QString toQString(QAnyStringView value) { return value.toString(); }

QString decodeNativeString(const std::string &value, QString *) {
  return toQString(value);
}
QByteArray decodeNativeString(const std::string &value, QByteArray *) {
  return QByteArray(value.data(), static_cast<qsizetype>(value.size()));
}
} // namespace qtluau
