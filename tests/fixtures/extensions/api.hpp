// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef WINGLUAUQT_TESTS_FIXTURES_EXTENSIONS_API_HPP
#define WINGLUAUQT_TESTS_FIXTURES_EXTENSIONS_API_HPP
#include <QObject>
#include <QDialog>
#include <QString>
#include <QAnyStringView>
#include <QVariant>
class ScriptService : public QObject {
    Q_OBJECT
public:
    using QObject::QObject;
private slots:
    QString echo(const QString &text) { return text + QStringLiteral("!"); }
    QString echoView(QAnyStringView text) { return text.toString(); }
    int add(int a, int b) { return a + b; }
    QVariant roundtrip(QVariant value) { return value; }
    QMap<QString, QVariant> identityMap(QMap<QString, QVariant> value) { return value; }
    QString kind(QString) { return QStringLiteral("string"); }
    QString kind(int) { return QStringLiteral("number"); }
    void hiddenSlot() {}
public slots:
    void publicSlot() {}
private:
    int secret() { return 42; }
};
class ScriptDialog : public QDialog {
    Q_OBJECT
public:
    using QDialog::QDialog;
private slots:
    QString title() { return windowTitle(); }
    void rename(QString value) { setWindowTitle(value); }
};

#endif // WINGLUAUQT_TESTS_FIXTURES_EXTENSIONS_API_HPP
