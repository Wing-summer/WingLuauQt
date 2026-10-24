-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

--!strict
local api = PublicApi()
local names: {string} = {"one", "two"}
local namesCopy = api:echo_names(names)
assert(namesCopy[1] == "one" and #namesCopy == 2)
namesCopy[1] = "changed"
assert(names[1] == "one")
assert((qt :: any).QStringList == nil and (qt :: any).QVariantList == nil and (qt :: any).QVariantMap == nil)
assert(api:add(20, 22) == 42)
local initialTitle: string = api.title
assert(initialTitle == "initial")
api.title = "from Luau"
api.counter = 7
assert(api.title == "from Luau" and api.counter == 7)
assert(api.version == 1)
assert(not pcall(function() api.version = 2 end))
api.values = {4, 5}
assert(api.values[2] == 5)
api.data = {name = "snapshot", nested = {1, 2}}
local snapshot = api.data
snapshot.name = "changed"
local currentData = api.data
assert(currentData.name == "snapshot")
api.data = snapshot
assert(api.data.name == "changed")
local internal = app.InternalApi()
assert(internal:multiply(4) == 8)
internal.factor = 3
assert(internal:multiply(4) == 12 and internal:secret(2) == 12)
local dialog = app.ExampleDialog()
dialog:set_window_title(api.title)
assert(dialog:window_title() == "from Luau")
assert(dialog:greeting() ~= "")
assert((dialog :: any).exec == nil)
local button = qt.QPushButton("ok")
button:set_parent(dialog)
assert(button:text() == "ok")

local tools = qt.QtTools()
assert(tools:label() == "custom qt module")

assert(reader.read_int() == 7)
ctl.write_int(42)
assert(reader.read_int() == 42)
assert(reader.read_int(1) == 43)
assert(reader.read_string() == "42")
assert((reader :: any).write_int == nil)
assert((ctl :: any).read_int == nil)
