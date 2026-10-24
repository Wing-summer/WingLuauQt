-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

--!strict
local button = qt.QPushButton("Hello")
local flat: boolean = button:is_flat()
button:set_auto_repeat(true)
local font = qt.QFont()
font:set_point_size(18)
button:set_font(font)
local size: number = button:font():point_size()
local text: string = button:text()
local length: number = ustring("hello"):length()
local nativeText = ustring("你好😀")
local luauText: string = nativeText:to_utf8()
local copiedText: string = ustring(nativeText):to_utf8()
local roundtripText: string = ustring(luauText):to_utf8()
local color = qt.QColor(10, 20, 30)
local red: number = color:red()
local browser = qt.QTextBrowser()
browser:set_plain_text("inherited")
local plain: string = browser:to_plain_text()

local values: {string} = {"a", "b"}
for index, value in values do
    local numeric: number = index
    local text: string = value
end
local box = qt.QVariant({answer = 42})
local name: string = box:type_name()
button:set_property("data", {color = color, values = values})
