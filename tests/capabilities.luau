-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

assert(bytearray == nil and qt.QByteArray == nil)
local text = ustring("hello")
assert(text:length() == 5)
assert(not pcall(function() text:append("x") end))
assert(not pcall(function() text:clear() end))
