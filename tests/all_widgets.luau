-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

-- Instantiate every wrapper type registered by runtime/qt_bindings.cpp.
local widgets = {
    qt.QWidget(), qt.QPushButton(), qt.QLabel(), qt.QLineEdit(), qt.QCheckBox(), qt.QComboBox(),
    qt.QFrame(), qt.QTextEdit(), qt.QPlainTextEdit(), qt.QRadioButton(), qt.QToolButton(),
    qt.QSpinBox(), qt.QDoubleSpinBox(), qt.QSlider(), qt.QScrollBar(), qt.QProgressBar(),
    qt.QListWidget(), qt.QTreeWidget(), qt.QTableWidget(), qt.QListView(), qt.QTreeView(),
    qt.QTableView(), qt.QTabWidget(), qt.QTabBar(), qt.QStackedWidget(), qt.QToolBox(),
    qt.QGroupBox(), qt.QSplitter(), qt.QScrollArea(), qt.QMenu(), qt.QMenuBar(), qt.QToolBar(),
    qt.QStatusBar(), qt.QDialogButtonBox(), qt.QDateEdit(), qt.QTimeEdit(), qt.QDateTimeEdit(),
    qt.QLCDNumber(), qt.QCalendarWidget(), qt.QDial(), qt.QKeySequenceEdit(), qt.QFontComboBox(),
    qt.QGraphicsView(), qt.QCommandLinkButton(), qt.QVBoxLayout(), qt.QHBoxLayout(), qt.QGridLayout()
}
for _, widget in ipairs(widgets) do
    assert(widget ~= nil)
end

assert(qt.QTextEdit("hello"):to_plain_text() == "hello")
assert(qt.QPlainTextEdit("plain"):to_plain_text() == "plain")
assert(qt.QRadioButton("radio"):text() == "radio")
assert(qt.QCommandLinkButton("command"):text() == "command")
assert(qt.QGroupBox("group"):title() == "group")
assert(qt.QMenu("menu"):title() == "menu")
assert(qt.QToolBar("toolbar"):window_title() == "toolbar")

local tabBar = qt.QTabBar()
assert(tabBar:count() == 0)
local toolbox = qt.QToolBox()
assert(toolbox:count() == 0)
assert(type(toolbox:current_index()) == "number")

local tableWidget = qt.QTableWidget()
assert(tableWidget:row_count() == 0)
tableWidget:clear()
local tree = qt.QTreeWidget()
assert(tree:top_level_item_count() == 0)
local list = qt.QListWidget()
list:add_item(ustring("item"))
assert(list:count() == 1)

-- Typed child lookups return concrete wrappers for controls loaded by QUiLoader.
local lookupRoot = qt.QWidget()
local lookupToolBox = qt.QToolBox()
lookupToolBox:set_object_name("lookupToolBox")
lookupToolBox:set_parent(lookupRoot)
local typedToolBox = lookupRoot:find_child_tool_box("lookupToolBox")
assert(typedToolBox:count() == 0)
local lookupDoubleSpin = qt.QDoubleSpinBox()
lookupDoubleSpin:set_object_name("lookupDoubleSpin")
lookupDoubleSpin:set_parent(lookupRoot)
local typedDoubleSpin = lookupRoot:find_child_double_spin_box("lookupDoubleSpin")
typedDoubleSpin:set_value(12.5)
assert(typedDoubleSpin:value() == 12.5)

assert(qt.QMainWindow == nil and qt.QDialog == nil and qt.QDockWidget == nil)
assert(qt.QFile == nil and qt.QThread == nil and qt.QProcess == nil)
assert(qt.QLibrary == nil and qt.QPluginLoader == nil and qt.QOpenGLWidget == nil)
print("all widget wrappers passed")
