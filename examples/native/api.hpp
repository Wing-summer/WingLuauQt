// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef WINGLUAUQT_EXAMPLES_NATIVE_API_HPP
#define WINGLUAUQT_EXAMPLES_NATIVE_API_HPP
#include <QObject>
#include <QDialog>
#include <QString>
#include <QStringList>
#include <QVariantMap>
#include <QList>
#include <qtluau/access.hpp>

class PublicApi : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString title READ title WRITE setTitle)
    Q_PROPERTY(QVariantMap data READ data WRITE setData)
public:
    int counter = 0;
    const int version = 1;
    QList<int> values{1, 2, 3};
    QStringList echoNames(const QStringList &names) const { return names; }
    int add(int a, int b) { return a + b; }
    QVariantMap data() const { return data_; }
    void setData(QVariantMap value) { data_ = std::move(value); }
    QString title() const { return title_; }
    void setTitle(QString value) { title_ = std::move(value); }
private:
    QVariantMap data_;
    QString title_ = QStringLiteral("initial");
};

class InternalApi : public QObject {
    Q_OBJECT
    friend struct qtluau::BindingAccess<InternalApi>;
protected:
    int factor = 2;
    int multiply(int value) const { return factor * value; }
private:
    int secret(int value) { return value + 10; }
};

class ExampleDialog : public QDialog {
    Q_OBJECT
public:
    using QDialog::QDialog;
    QString greeting() const { return QStringLiteral("Hello from a QWidget view of QDialog"); }
};

class QtTools : public QObject {
    Q_OBJECT
public:
    QString label() const { return QStringLiteral("custom qt module"); }
};

// The host owns this service. Its private slots are exposed in separate modules.
class HostServices : public QObject {
    Q_OBJECT
private slots:
    int readInt(const QObject *sender) const { return sender ? value_ : -1; }
    int readInt(const QObject *sender, int increment) const { return sender ? value_ + increment : -1; }
public:
    QString readString(const QObject *sender) const { return sender ? QString::number(value_) : QString(); }
private slots:
    void writeInt(const QObject *sender, int value) { if (sender) value_ = value; }
private:
    int value_ = 7;
};

#endif // WINGLUAUQT_EXAMPLES_NATIVE_API_HPP
