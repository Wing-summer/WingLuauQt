-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

--!strict
local service = app.ScriptService()
local text: string = service:echo_view("hello")
local total: number = service:add(1, 2)
local kind: string = service:kind(2)
local map: {[string]: any} = service:identity_map({name = text})
local dialog = app.ScriptDialog()
dialog:resize(320, 200)
dialog:set_window_title(kind)
dialog:rename(text)
local title: string = dialog:title()
return {total = total, map = map, title = title}
