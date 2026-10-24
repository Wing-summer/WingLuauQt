-- Copyright (c) 2026, wingsummer
-- SPDX-License-Identifier: BSD-3-Clause
-- See LICENSE in the project root for license information.

assert(ustring == nil and bytearray == nil and stringlist == nil and variant == nil)
assert(qt.QString == text and qt.QByteArray == bytes)
assert(qt.QVariant == box)
assert(qt.QStringList == nil and qt.QVariantList == nil and qt.QVariantMap == nil)
assert(text("abc"):length() == 3)
assert(strings == nil and sequence == nil and dictionary == nil)
assert(box({x = 1}):to_value().x == 1)

assert(qt.QColor == color and qt.QSpinBox == spinner)
local c = color(1, 2, 3)
assert(c:red() == 1 and c.green == nil)
local spin = spinner()
spin:set_value(7)
assert(spin:value() == 7)
