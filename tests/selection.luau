-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

assert(qt.QWidget ~= nil)
assert(qt.QPushButton == nil)
assert(qt.QLabel == nil)
assert(hostPanel.find_child_push_button == nil)
assert(hostPanel.find_child_label == nil)
assert(qt.QMainWindow == nil and qt.QDialog == nil and qt.QDockWidget == nil)
assert(qt.QFile == nil and qt.QThread == nil and qt.QProcess == nil)
print("selected-class boundary assertions passed")
