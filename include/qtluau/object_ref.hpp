// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_OBJECT_REF_HPP
#define QTLUAU_INCLUDE_QTLUAU_OBJECT_REF_HPP
#include <QObject>
#include <QPointer>
#include <QThread>
#include <memory>
#include <stdexcept>

namespace qtluau {
// Shared lifetime token: borrowed objects may disappear while a Luau value survives.
template<class T> class QtObjectRef {
    struct Lifetime {
        QPointer<T> object;
        bool owned;
        Lifetime(T *value, bool own) : object(value), owned(own) {}
        ~Lifetime() {
            if (owned && object) {
                QObject *base = object.data();
                if (base->thread() == QThread::currentThread()) delete base;
                else base->deleteLater();
            }
        }
    };
    std::shared_ptr<Lifetime> lifetime_;
public:
    QtObjectRef() : QtObjectRef(new T, true) {}
    explicit QtObjectRef(T *object, bool owned = false)
        : lifetime_(std::make_shared<Lifetime>(object, owned)) {}
    T *get() const {
        auto *object = lifetime_->object.data();
        if (!object) throw std::runtime_error("QObject has been deleted");
        if (static_cast<QObject *>(object)->thread() != QThread::currentThread())
            throw std::runtime_error("QObject accessed from another thread");
        return object;
    }
};
}

#endif // QTLUAU_INCLUDE_QTLUAU_OBJECT_REF_HPP
