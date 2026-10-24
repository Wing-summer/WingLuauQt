-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

-- This is the default executable's end-to-end integration test.
local text = ustring("Hello")
assert(text:length() == 5)
text:append(", Luau!")
assert(text:to_utf8() == "Hello, Luau!")
assert(text:at(0) == "H")

-- QString keeps its userdata surface; UTF-8 strings round-trip without losing NUL.
local utf8 = "中文😀\0end"
local unicode = ustring(utf8)
assert(unicode:to_utf8() == utf8)
assert(ustring(unicode:to_utf8()):to_utf8() == utf8)
local unicodeCopy = ustring(unicode)
unicodeCopy:append("!")
assert(unicode:to_utf8() == utf8 and unicodeCopy:to_utf8() == utf8 .. "!")

local bytes = bytearray("abc")
assert(bytes:size() == 3)
assert(bytes:at(1) == 98)
bytes:append("d")
assert(bytes:to_std_string() == "abcd")

-- A host-owned content widget can be passed to Luau without binding host window classes.
assert(hostPanel:object_name() == "host-panel")
hostPanel:set_window_title("updated by Luau")
assert(hostPanel:window_title() == "updated by Luau")
hostPanel:set_tool_tip(ustring("tooltip via alias"))

-- The namespace aliases refer to exactly the same class tables as the global aliases.
assert(qt.QString == ustring)
assert(qt.QByteArray == bytearray)

assert(stringlist == nil and qt.QStringList == nil)
local values = {}
table.insert(values, "one")
table.insert(values, "two")
assert((#values) == 2)
assert(values[2] == "two")

local root = qt.QWidget()
root:set_window_title("Qt / Luau binding test")
root:resize(480, 320)
local layout = qt.QVBoxLayout()
root:set_layout(layout)

-- Load a Designer UI from an in-memory XML string and return the embedded QWidget surface.
local embedded = qt.load_ui_widget_xml([==[
<?xml version="1.0" encoding="UTF-8"?>
<ui version="4.0">
 <class>EmbeddedPanel</class>
 <widget class="QWidget" name="EmbeddedPanel">
  <property name="windowTitle"><string>Loaded XML</string></property>
  <layout class="QVBoxLayout" name="innerLayout">
   <item><widget class="QLabel" name="embeddedLabel"><property name="text"><string>From XML</string></property></widget></item>
   <item><widget class="QPushButton" name="embeddedButton"><property name="text"><string>UI action</string></property></widget></item>
  </layout>
 </widget>
 <resources/>
 <connections/>
</ui>
]==])
assert(embedded:object_name() == "EmbeddedPanel")
assert(embedded:property("windowTitle") == "Loaded XML")
assert(embedded:set_property("windowTitle", ustring("changed through alias")))
assert(embedded:property("windowTitle") == "changed through alias")
local embeddedLabel = embedded:find_child_label("embeddedLabel")
assert(embeddedLabel:text() == "From XML")
embeddedLabel:set_text(ustring("from named child"))
assert(embeddedLabel:text() == "from named child")
local embeddedButton = embedded:find_child_push_button("embeddedButton")
assert(embeddedButton:text() == "UI action")
embeddedButton:set_text("changed UI button")
assert(embeddedButton:text() == "changed UI button")
local embeddedClicked = false
embeddedButton:connect("clicked", function() embeddedClicked = true end)
embeddedButton:click()
assert(embeddedClicked)
local unsafeAssetLoaded = pcall(function()
    qt.load_ui_widget_xml([==[
<ui version="4.0"><class>Unsafe</class><widget class="QWidget" name="Unsafe">
<widget class="QLabel" name="leak"><property name="pixmap"><pixmap>/etc/passwd</pixmap></property></widget>
</widget><resources/><connections/></ui>
]==])
end)
assert(not unsafeAssetLoaded, "inline UI XML must not access arbitrary filesystem assets")
embedded:set_parent(root)
layout:add_widget(embedded)

local label = qt.QLabel("ready")
layout:add_widget(label)
assert(label:text() == "ready")
label:set_text("updated")
assert(label:text() == "updated")
local typedText = ustring("from common alias")
label:set_text(typedText)
assert(label:text() == "from common alias")
assert(qt.QLabel(typedText):text() == "from common alias")

local edit = qt.QLineEdit(ustring("input"))
edit:set_placeholder_text("type here")
layout:add_widget(edit)
assert(edit:text() == "input")
assert(edit:placeholder_text() == "type here")
edit:set_text("edited")
assert(edit:text() == "edited")

local check = qt.QCheckBox("enabled")
check:set_checked(true)
assert(check:is_checked())
layout:add_widget(check)

local combo = qt.QComboBox()
combo:add_item("alpha")
combo:add_item(ustring("beta"))
assert(combo:count() == 2)
combo:set_current_index(1)
assert(combo:current_text() == "beta")
layout:add_widget(combo)

-- Generic adapters expose only writable Qt meta-properties rather than arbitrary QObject APIs.
local spin = qt.QSpinBox()
spin:set_value(7)
assert(spin:value() == 7)
assert(spin:property("value") == 7)
layout:add_widget(spin)

local editor = qt.QTextEdit()
assert(editor:set_property("placeholderText", "write here"))
assert(editor:property("placeholderText") == "write here")
layout:add_widget(editor)

local radio = qt.QRadioButton("choice")
assert(radio:set_property("checked", true))
assert(radio:property("checked") == true)
layout:add_widget(radio)

local list = qt.QListWidget()
assert(list:is_enabled())
list:add_item("first")
list:add_item(ustring("second"))
assert(list:count() == 2)
layout:add_widget(list)

local tabs = qt.QTabWidget()
assert(tabs:is_enabled())
layout:add_widget(tabs)

local button = qt.QPushButton("Click")
assert(not pcall(function() button:connect("missingSignal", function() end) end))
assert(not pcall(function() button:connect("clicked", 42 :: any) end))
local clicked = 0
button:connect("clicked", function()
    clicked += 1
    label:set_text("clicked")
end)
layout:add_widget(button)
button:click()
assert(clicked == 1)
assert(label:text() == "clicked")

-- Layout access and selected types work while unsafe/unwanted types stay absent.
assert(layout:spacing() >= -1)
assert(qt.QMainWindow == nil)
assert(qt.QDialog == nil)
assert(qt.QDockWidget == nil)
assert(qt.QFile == nil)
assert(qt.QThread == nil)
assert(qt.QProcess == nil)
assert(qt.QLibrary == nil)
assert(qt.QPluginLoader == nil)
assert(qt.QOpenGLWidget == nil)
root:show()
assert(root:is_visible())
root:hide()

print("runtime assertions passed")
