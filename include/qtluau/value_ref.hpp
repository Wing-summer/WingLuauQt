// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_VALUE_REF_HPP
#define QTLUAU_INCLUDE_QTLUAU_VALUE_REF_HPP
#include <QAnyStringView>
#include <QByteArray>
#include <QString>
#include <string>
#include <utility>
namespace qtluau {
std::string toUtf8String(QAnyStringView value);
QString toQString(QAnyStringView value);
QString decodeNativeString(const std::string &value, QString *);
QByteArray decodeNativeString(const std::string &value, QByteArray *);
// Native API registration is generated; this template owns only a value.
template <class Native> class QtValueRef {
public:
  QtValueRef() = default;
  explicit QtValueRef(Native value) : value_(std::move(value)) {}
  explicit QtValueRef(const std::string &value)
      : value_(decodeNativeString(value, static_cast<Native *>(nullptr))) {}
  Native value() const { return value_; }
  Native &native() { return value_; }
  const Native &native() const { return value_; }

private:
  Native value_;
};
} // namespace qtluau
#endif
