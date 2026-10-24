// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include <QApplication>
#include <QByteArray>
#include <QDebug>
#include <QFile>
#include <QFileInfo>
#include <QLabel>
#include <QWidget>

#include "profiles.hpp"

#include "qtluau/bindings.hpp"
#include "qtluau/execution.hpp"

#include <iostream>
#include <memory>
#include <stdexcept>

namespace {
QString argValue(int argc, char **argv, const QString &prefix) {
  for (int i = 1; i < argc; ++i) {
    const QString arg = QString::fromLocal8Bit(argv[i]);
    if (arg.startsWith(prefix)) {
      return arg.mid(prefix.size());
    }
  }
  return {};
}

QString readTextFile(const QString &path) {
  QFile f(path);
  if (!f.open(QIODevice::ReadOnly | QIODevice::Text)) {
    throw std::runtime_error((QStringLiteral("Cannot read test script: ") +
                              path + QStringLiteral(": ") + f.errorString())
                                 .toStdString());
  }
  return QString::fromUtf8(f.readAll());
}
} // namespace

int main(int argc, char **argv) {
  // Parse application arguments before QApplication can consume or rewrite
  // argv.
  const QString profile = argValue(argc, argv, QStringLiteral("--profile="));
  const QString scriptArg = argValue(argc, argv, QStringLiteral("--script="));
  const QString scriptPath = scriptArg.isEmpty()
                                 ? QStringLiteral(QTLUAU_DEFAULT_TEST_SCRIPT)
                                 : scriptArg;

  if (qEnvironmentVariableIsEmpty("QT_QPA_PLATFORM") &&
      qEnvironmentVariableIsEmpty("DISPLAY") &&
      qEnvironmentVariableIsEmpty("WAYLAND_DISPLAY")) {
    qputenv("QT_QPA_PLATFORM", QByteArray("offscreen"));
  }
  QApplication app(argc, argv);
  QWidget hostPanel;
  hostPanel.setObjectName(QStringLiteral("host-panel"));

  lua_State *L = luaL_newstate();
  if (!L) {
    std::cerr << "ERROR: luaL_newstate failed\n";
    return 2;
  }

  int result = 0;
  try {
    luaL_openlibs(L);
    const QStringList allowedRoots = testAllowedUiRoots(profile);

    // Exercise the host-side loader API as well as the Luau wrapper. This makes
    // sure the returned QWidget can be directly inserted into a host-owned
    // custom main window.
    if (!allowedRoots.isEmpty()) {
      QString nativeLoadError;
      std::unique_ptr<QWidget> nativeUi(qtluau::loadUiWidgetFileNative(
          QStringLiteral("tests/fixtures/ui/sample.ui"), allowedRoots,
          &nativeLoadError));
      if (!nativeUi) {
        throw std::runtime_error(
            (QStringLiteral("Native UI load failed: ") + nativeLoadError)
                .toStdString());
      }
      if (nativeUi->objectName() != QStringLiteral("EmbeddedSample")) {
        throw std::runtime_error(
            "Native UI loader returned an unexpected root widget");
      }
      const auto *sampleLabel =
          nativeUi->findChild<QLabel *>(QStringLiteral("sampleLabel"));
      if (!sampleLabel ||
          sampleLabel->text() != QStringLiteral("Loaded child")) {
        throw std::runtime_error(
            "Native UI loader did not preserve child widgets/properties");
      }
    }

    registerTestBindings(L, profile);
    qtluau::pushQtWidget(L, &hostPanel, false);
    lua_setglobal(L, "hostPanel");
    QString error;
    if (!qtluau::executeLuau(L, readTextFile(scriptPath), &error)) {
      std::cerr << "Luau integration test failed:\n"
                << error.toStdString() << '\n';
      result = 1;
    } else {
      std::cout << "All integrated Luau / Qt binding tests passed.\n";
    }
  } catch (const std::exception &e) {
    std::cerr << "ERROR: " << e.what() << '\n';
    result = 1;
  }

  qtluau::clearLuaCallbacks(L);
  lua_close(L);
  return result;
}
