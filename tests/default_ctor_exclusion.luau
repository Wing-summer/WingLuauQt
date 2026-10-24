-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

assert(qt.QPushButton ~= nil)
assert(not pcall(function() qt.QPushButton() end), "zero-argument constructor exclusion was ignored")
local button = qt.QPushButton("text constructor remains available")
assert(button:text() == "text constructor remains available")
print("default constructor exclusion assertions passed")
