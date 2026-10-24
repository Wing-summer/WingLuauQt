// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef WINGLUAUQT_TESTS_FIXTURES_HEADERS_B_VALUE_H
#define WINGLUAUQT_TESTS_FIXTURES_HEADERS_B_VALUE_H
namespace fixture::b {
struct Value {
    Value() = default;
    bool enabled() const { return true; }
};
}

#endif // WINGLUAUQT_TESTS_FIXTURES_HEADERS_B_VALUE_H
