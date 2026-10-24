// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#include "qtluau/ui_support.hpp"
#include <QBuffer>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QSet>
#include <QXmlStreamReader>

namespace qtluau {
namespace {
constexpr qsizetype kMaxUiBytes = 16 * 1024 * 1024;
bool pathIsWithin(const QString &filePath, const QString &rootPath) {
  const QString file = QDir::cleanPath(QDir::fromNativeSeparators(filePath));
  const QString root = QDir::cleanPath(QDir::fromNativeSeparators(rootPath));
#ifdef Q_OS_WIN
  constexpr Qt::CaseSensitivity sensitivity = Qt::CaseInsensitive;
#else
  constexpr Qt::CaseSensitivity sensitivity = Qt::CaseSensitive;
#endif
  if (file.compare(root, sensitivity) == 0) {
    return true;
  }
  QString prefix = root;
  if (!prefix.endsWith(u'/')) {
    prefix += u'/';
  }
  return file.startsWith(prefix, sensitivity);
}

bool isQtResourcePath(const QString &path) {
  return path.startsWith(QStringLiteral(":/")) ||
         path.startsWith(QStringLiteral("qrc:/"));
}

void validateUiAssetReferences(const QByteArray &xml, const QDir &baseDirectory,
                               const QStringList &allowedRoots,
                               bool resourcesOnly) {
  static const QSet<QString> assetElements = {
      QStringLiteral("pixmap"),     QStringLiteral("normaloff"),
      QStringLiteral("normalon"),   QStringLiteral("disabledoff"),
      QStringLiteral("disabledon"), QStringLiteral("activeoff"),
      QStringLiteral("activeon"),   QStringLiteral("selectedoff"),
      QStringLiteral("selectedon")};
  QXmlStreamReader reader(xml);
  while (!reader.atEnd()) {
    reader.readNext();
    if (!reader.isStartElement() ||
        !assetElements.contains(reader.name().toString())) {
      continue;
    }
    const QString elementName = reader.name().toString();
    QString asset;
    while (!reader.atEnd()) {
      reader.readNext();
      if (reader.isCharacters()) {
        asset += reader.text().toString();
      }
      if (reader.isEndElement() && reader.name().toString() == elementName) {
        break;
      }
    }
    asset = asset.trimmed();
    if (asset.isEmpty() || isQtResourcePath(asset)) {
      continue;
    }
    if (resourcesOnly) {
      throw std::invalid_argument("UI XML may reference only compiled Qt "
                                  "resources (:/... or qrc:/...)");
    }

    const QString candidatePath = baseDirectory.absoluteFilePath(asset);
    const QFileInfo assetInfo(candidatePath);
    const QString canonicalAsset = assetInfo.canonicalFilePath();
    if (canonicalAsset.isEmpty() || !assetInfo.isFile()) {
      throw std::invalid_argument(
          (QStringLiteral("UI asset does not resolve to a regular file: ") +
           asset)
              .toStdString());
    }
    bool allowed = false;
    for (const QString &configuredRoot : allowedRoots) {
      const QFileInfo rootInfo(configuredRoot);
      const QString canonicalRoot = rootInfo.canonicalFilePath();
      if (!canonicalRoot.isEmpty() && rootInfo.isDir() &&
          pathIsWithin(canonicalAsset, canonicalRoot)) {
        allowed = true;
        break;
      }
    }
    if (!allowed) {
      throw std::invalid_argument(
          (QStringLiteral("UI asset is outside qt.ui_tools.allowed_roots: ") +
           asset)
              .toStdString());
    }
  }
  if (reader.hasError()) {
    throw std::invalid_argument(
        (QStringLiteral("Invalid UI XML: ") + reader.errorString())
            .toStdString());
  }
}

QByteArray readLimited(QFile &file) {
  if (!file.open(QIODevice::ReadOnly)) {
    throw std::runtime_error(
        (QStringLiteral("Unable to read UI file: ") + file.errorString())
            .toStdString());
  }
  const QByteArray bytes = file.read(kMaxUiBytes + 1);
  if (bytes.size() > kMaxUiBytes) {
    throw std::invalid_argument("UI file exceeds the 16 MiB safety limit");
  }
  if (file.error() != QFileDevice::NoError) {
    throw std::runtime_error(
        (QStringLiteral("Unable to read UI file: ") + file.errorString())
            .toStdString());
  }
  return bytes;
}

QWidget *loadUiXmlRaw(const QByteArray &bytes) {
  if (bytes.isEmpty()) {
    throw std::invalid_argument("UI XML must not be empty");
  }
  if (bytes.size() > kMaxUiBytes) {
    throw std::invalid_argument("UI XML exceeds the 16 MiB safety limit");
  }
  const QDir resourceRoot(QStringLiteral(":/"));
  validateUiAssetReferences(bytes, resourceRoot, {}, true);
  QString error;
  QWidget *widget = detail::loadUiDocument(bytes, resourceRoot, &error);
  if (!widget) {
    throw std::runtime_error(
        (QStringLiteral("Unable to load UI XML: ") + error).toStdString());
  }
  return widget;
}

QWidget *loadUiFileRaw(const QString &input, const QStringList &allowedRoots) {
  if (input.startsWith(QStringLiteral(":/"))) {
    QFile file(input);
    const QByteArray bytes = readLimited(file);
    const QDir resourceRoot(QStringLiteral(":/"));
    validateUiAssetReferences(bytes, resourceRoot, {}, true);
    QString error;
    QWidget *widget = detail::loadUiDocument(bytes, resourceRoot, &error);
    if (!widget) {
      throw std::runtime_error(
          (QStringLiteral("Unable to load UI resource: ") + error)
              .toStdString());
    }
    return widget;
  }

  const QFileInfo inputInfo(input);
  const QString canonicalInput = inputInfo.canonicalFilePath();
  if (canonicalInput.isEmpty() || !inputInfo.isFile()) {
    throw std::invalid_argument(
        "UI path does not resolve to an existing regular file");
  }
  if (inputInfo.suffix().compare(QStringLiteral("ui"), Qt::CaseInsensitive) !=
      0) {
    throw std::invalid_argument("Only Qt Designer .ui files can be loaded");
  }

  bool allowed = false;
  for (const QString &configuredRoot : allowedRoots) {
    const QFileInfo rootInfo(configuredRoot);
    const QString canonicalRoot = rootInfo.canonicalFilePath();
    if (!canonicalRoot.isEmpty() && rootInfo.isDir() &&
        pathIsWithin(canonicalInput, canonicalRoot)) {
      allowed = true;
      break;
    }
  }
  if (!allowed) {
    throw std::invalid_argument("UI file is outside qt.ui_tools.allowed_roots; "
                                "arbitrary filesystem reads are disabled");
  }

  QFile file(canonicalInput);
  const QByteArray bytes = readLimited(file);
  const QDir workingDirectory = QFileInfo(canonicalInput).absoluteDir();
  validateUiAssetReferences(bytes, workingDirectory, allowedRoots, false);
  QString error;
  QWidget *widget = detail::loadUiDocument(bytes, workingDirectory, &error);
  if (!widget) {
    throw std::runtime_error(
        (QStringLiteral("Unable to load UI file: ") + error).toStdString());
  }
  return widget;
}

} // namespace
namespace detail {
QtWidgetRef loadUiXml(const std::string &xml) {
  return QtWidgetRef(
      loadUiXmlRaw(QByteArray(xml.data(), static_cast<qsizetype>(xml.size()))),
      true);
}

QtWidgetRef loadUiFile(const std::string &pathUtf8,
                       const QStringList &allowedRoots) {
  const QString path = QString::fromUtf8(
      pathUtf8.data(), static_cast<qsizetype>(pathUtf8.size()));
  return QtWidgetRef(loadUiFileRaw(path, allowedRoots), true);
}

} // namespace detail
QWidget *loadUiWidgetXmlNative(const QByteArray &xml, QString *errorMessage) {
  try {
    return loadUiXmlRaw(xml);
  } catch (const std::exception &e) {
    if (errorMessage) {
      *errorMessage = QString::fromUtf8(e.what());
    }
    return nullptr;
  }
}

QWidget *loadUiWidgetFileNative(const QString &path,
                                const QStringList &allowedRoots,
                                QString *errorMessage) {
  try {
    return loadUiFileRaw(path, allowedRoots);
  } catch (const std::exception &e) {
    if (errorMessage) {
      *errorMessage = QString::fromUtf8(e.what());
    }
    return nullptr;
  }
}

} // namespace qtluau
