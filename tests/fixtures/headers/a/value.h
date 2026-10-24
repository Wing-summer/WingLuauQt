// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef WINGLUAUQT_TESTS_FIXTURES_HEADERS_A_VALUE_H
#define WINGLUAUQT_TESTS_FIXTURES_HEADERS_A_VALUE_H
#include <string>
#include "../common.h"
namespace fixture::a {
struct Value : public fixture::Base {
    int count = 0;
    Value() = default;
    explicit Value(int n) : count(n) {}
    using iterator = int*;
    iterator begin() { return &count; }
    iterator end() { return &count + 1; }
    int number() const { return count; }
    int number(int add) const { return count + add; }
    std::string label() const { return "a"; }
};
class Abstract {
public:
    virtual ~Abstract() = default;
    virtual int run() = 0;
};
}

#endif // WINGLUAUQT_TESTS_FIXTURES_HEADERS_A_VALUE_H
