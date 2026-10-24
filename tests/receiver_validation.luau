-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

local w = qt.QWidget()
local function rejects(f)
    local ok, message = pcall(f)
    assert(not ok, "invalid receiver was accepted")
    assert(type(message) == "string")
end
rejects(function() w.show() end)
rejects(function() w.show(nil) end)
rejects(function() w.show({}) end)
rejects(function() w.show(ustring("wrong receiver")) end)
local show = w.show
rejects(function() show() end)
rejects(function() w.resize(10, 20) end)
local text = ustring("valid")
rejects(function() text.length() end)
rejects(function() text.length(nil) end)
local color = qt.QColor()
rejects(function() color.red() end)
rejects(function() color.red(nil) end)
local button = qt.QPushButton("generated")
rejects(function() button.is_flat() end)
rejects(function() button.set_flat(true) end)
button:set_flat(true)
assert(button:is_flat())
w:resize(100, 100)
w:show()
w.show(w)
w:hide()
assert(text:length() == 5)
