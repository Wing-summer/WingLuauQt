-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

assert(qt.QWidget ~= nil)
assert(qt.QPushButton == nil)
assert(hostPanel.find_child_push_button == nil)
assert(hostPanel.move_to_thread == nil)
local widget = qt.QWidget()
widget:set_window_title("class exclusion remains isolated")
assert(widget:window_title() == "class exclusion remains isolated")
print("class exclusion assertions passed")
