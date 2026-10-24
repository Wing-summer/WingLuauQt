-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

local s = textvalue("hello")
assert(s:to_utf8() == "hello")
local d = rawdata("abc")
assert(d:to_std_string() == "abc")
assert(qt.QString == textvalue)
assert(qt.QByteArray == rawdata)
local label = qt.QLabel(s)
assert(label:text() == "hello")
label:set_text(textvalue("new"))
assert(label:text() == "new")
assert(qt.load_ui_widget_xml == nil)
assert(qt.QMainWindow == nil and qt.QDialog == nil and qt.QDockWidget == nil)
print("custom alias assertions passed")

local textCopy = textvalue(s)
assert(textCopy:to_utf8() == s:to_utf8())
local bytesCopy = rawdata(d)
assert(bytesCopy:to_std_string() == d:to_std_string())
assert(qt.QString(textCopy):to_utf8() == s:to_utf8())
assert(qt.QByteArray(bytesCopy):to_std_string() == d:to_std_string())
