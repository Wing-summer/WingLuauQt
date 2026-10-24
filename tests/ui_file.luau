-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

local embedded = qt.load_ui_widget_file("tests/fixtures/ui/sample.ui")
assert(embedded:object_name() == "EmbeddedSample")
assert(embedded:property("windowTitle") == "Loaded from .ui")
local sampleLabel = embedded:find_child_label("sampleLabel")
assert(sampleLabel:text() == "Loaded child")
local sampleButton = embedded:find_child_push_button("sampleButton")
assert(sampleButton:text() == "Go")
local clickCount = 0
sampleButton:connect("clicked", function() clickCount += 1 end)
sampleButton:click()
assert(clickCount == 1)

local denied = pcall(function()
    qt.load_ui_widget_file("CMakeLists.txt")
end)
assert(not denied, "non-.ui file should be rejected")
local unsafeAsset = pcall(function()
    qt.load_ui_widget_file("tests/fixtures/ui/unsafe_asset.ui")
end)
assert(not unsafeAsset, "UI image references must remain inside configured read roots")

assert(qt.QMainWindow == nil)
assert(qt.QDialog == nil)
assert(qt.QDockWidget == nil)
print("UI file loader assertions passed")

-- QColumnView comes from SDK discovery, rather than a handwritten loader list.
local column = qt.load_ui_widget_xml('<ui version="4.0"><class>Columns</class><widget class="QColumnView" name="columns"/></ui>')
assert(column:object_name() == "columns")
