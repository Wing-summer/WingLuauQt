-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

local button = qt.QPushButton()
assert(button.set_text ~= nil)
assert(button.click == nil)
assert(button.set_style_sheet == nil)
local ok = pcall(function()
    qt.QPushButton("text constructor is excluded")
end)
assert(not ok)

-- A typed child lookup must not bypass a concrete-class member exclusion.
local parent = qt.QWidget()
local child = qt.QPushButton()
child:set_object_name("excluded-click-child")
child:set_parent(parent)
local found = parent:find_child_push_button("excluded-click-child")
assert(found.set_text ~= nil)
assert(found.click == nil)
assert(found.set_style_sheet == nil)
print("member exclusion assertions passed")
