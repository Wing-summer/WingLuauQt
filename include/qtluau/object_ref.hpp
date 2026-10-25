// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.
#ifndef QTLUAU_INCLUDE_QTLUAU_OBJECT_REF_HPP
#define QTLUAU_INCLUDE_QTLUAU_OBJECT_REF_HPP
#include "qtluau/qobject_value.hpp"
namespace qtluau {
template <class T> class QtObjectRef : public QObjectRef {
public:
    QtObjectRef() : QtObjectRef(new T, true) {}
    explicit QtObjectRef(T *object, bool owned = false, bool readOnly = false)
        : QObjectRef(object, owned, readOnly) {}
    T *get() const {
        auto *object = qobject_cast<T *>(QObjectRef::get());
        if (!object) {
            throw std::runtime_error("Incompatible QObject type");
        }
        return object;
    }
};
}
#endif
