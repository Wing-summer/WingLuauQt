// Copyright (c) 2026, wingsummer
// SPDX-License-Identifier: BSD-3-Clause
// See LICENSE in the project root for license information.

#ifndef QTLUAU_INCLUDE_QTLUAU_ACCESS_HPP
#define QTLUAU_INCLUDE_QTLUAU_ACCESS_HPP
namespace qtluau {
// Opt in inside a native class: friend struct qtluau::BindingAccess<MyClass>;
// Specializations are generated only when non_public="friend" is requested.
template<class T> struct BindingAccess;
}

#endif // QTLUAU_INCLUDE_QTLUAU_ACCESS_HPP
