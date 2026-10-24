// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef WINGLUAUQT_TESTS_FIXTURES_HEADERS_COMMON_H
#define WINGLUAUQT_TESTS_FIXTURES_HEADERS_COMMON_H
namespace fixture {
struct Base {
    int baseValue() const { return 7; }
};
struct FromInclude {
    int fromInclude() const { return 9; }
};
}

#endif // WINGLUAUQT_TESTS_FIXTURES_HEADERS_COMMON_H
