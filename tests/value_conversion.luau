-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

assert(stringlist == nil and variantlist == nil and variantmap == nil)
assert(qt.QStringList == nil and qt.QVariantList == nil and qt.QVariantMap == nil)
local list = variant({"一", "two"}, "QStringList"):to_value()
assert(type(list) == "table" and list[1] == "一")
local joined = ""
for i, value in list do joined ..= tostring(i) .. value end
assert(joined == "1一2two")
table.insert(list, "three")
assert(#list == 3)
assert(not pcall(function() variant({1}, "QStringList") end))
-- Exercise SDK-discovered value APIs and native default arguments.
local discoveredColor = qt.QColor(20, 40, 60)
assert(discoveredColor:lighter():is_valid())
assert(type(discoveredColor:name()) == "string")
local discoveredFont = qt.QFont()
discoveredFont:set_pixel_size(18)
assert(discoveredFont:pixel_size() == 18)
discoveredFont:set_families({"Sans"})
assert(type(discoveredFont:families()) == "table" and #discoveredFont:families() == 1)

local widget = qt.QWidget()
local original = {nested = {1, true, "你好", qt.null}, color = qt.QColor(1, 2, 3)}
assert(widget:set_property("payload", original))
original.nested[1] = 99
local copy = widget:property("payload")
assert(copy.nested[1] == 1 and copy.nested[4] == qt.null)
assert(copy.color:green() == 2)
copy.nested[1] = 55
assert(widget:property("payload").nested[1] == 1)
local boxed = variant({answer = 42}, "QVariantMap")
assert(boxed:is_valid() and boxed:type_name() == "QVariantMap")
assert(boxed:to_value().answer == 42)
local invalid = variant()
assert(not invalid:is_valid() and invalid:to_value() == nil)
assert(variant(qt.null):is_null())
local emptyMap = variant({}, "QVariantMap")
assert(emptyMap:type_name() == "QVariantMap")
local bytes = bytearray("a\0\255")
assert(variant(bytes):to_value() == "a\0\255")
local combo = qt.QComboBox()
combo:add_item("first")
combo:set_item_data(0, {values = {"a", "b"}}, 256)
assert(combo:item_data(0, 256).values[2] == "b")
combo:add_items({"second", "third"})
assert(combo:count() == 3)
local cycle = {}; cycle.self = cycle
assert(not pcall(function() variant(cycle) end))
assert(not pcall(function() variant({[1] = 1, [3] = 3}) end))
assert(not pcall(function() variant({[1] = 1, key = 2}) end))
assert(not pcall(function() variant(function() end) end))
assert(not pcall(function() variant({}, "QObject*") end))
assert(widget:set_property("payload", nil) and widget:property("payload") == nil)
local sequence = variant({1, qt.null, false}):to_value()
local count = 0
for i, value in ipairs(sequence) do count += 1 end
assert(count == 3)
local mapping = variant({first = 1, second = 2}):to_value()
local sum = 0
for _, value in pairs(mapping) do sum += value end
assert(sum == 3)
-- The host VM preserves signed 64-bit integers exactly.
local huge = variant("9223372036854775807", "qlonglong")
assert(huge:type_name() == "qlonglong")
assert(type(huge:to_value()) == "integer")
assert(tostring(huge:to_value()) == "9223372036854775807")
assert(not pcall(function() combo:add_items({1}) end))

local splitter = qt.QSplitter()
assert(type(splitter:sizes()) == "table")
assert(not pcall(function() splitter:set_sizes({1.5}) end))
local deep = {}; local tail = deep
for _ = 1, 70 do tail.next = {}; tail = tail.next end
assert(not pcall(function() variant(deep) end))
-- Failed conversions leave the Luau stack usable.
assert(variant({ok = true}):to_value().ok)
