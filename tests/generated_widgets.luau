-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

local button = qt.QPushButton("generated methods")
button:set_flat(true)
assert(button:is_flat())
button:set_auto_repeat(true)
assert(button:auto_repeat())
local font = qt.QFont()
font:set_point_size(18)
font:set_bold(true)
button:set_font(font)
assert(button:font():point_size() == 18)
assert(button:font():bold())
local color = qt.QColor(10, 20, 30)
assert(color:red() == 10 and color:green() == 20 and color:blue() == 30)
local browser = qt.QTextBrowser()
browser:set_plain_text("inherited generated API")
assert(browser:to_plain_text() == "inherited generated API")
assert(qt.QMainWindow == nil and qt.QThread == nil and qt.QDialog == nil)
