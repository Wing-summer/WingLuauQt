# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets UiTools)
include("${CMAKE_CURRENT_LIST_DIR}/WingLuauQtPython.cmake")
if(QTLUAU_BUILD_TESTS)
  wingluauqt_prepare_python(DEV)
else()
  wingluauqt_prepare_python()
endif()
find_package(Threads REQUIRED)

set(LUAU_SOURCE_DIR "${PROJECT_SOURCE_DIR}/3rdparty/luau" CACHE PATH "Luau source checkout")
set(LUABRIDGE3_SOURCE_DIR "${PROJECT_SOURCE_DIR}/3rdparty/LuaBridge3" CACHE PATH "LuaBridge3 source checkout")
if(NOT EXISTS "${LUAU_SOURCE_DIR}/CMakeLists.txt")
  message(FATAL_ERROR "Luau checkout missing: ${LUAU_SOURCE_DIR}. See README.md for dependency setup.")
endif()
if(NOT TARGET Luau.VM)
  set(LUAU_BUILD_CLI OFF CACHE BOOL "" FORCE)
  set(LUAU_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  add_subdirectory("${LUAU_SOURCE_DIR}" "${PROJECT_BINARY_DIR}/_deps/luau" EXCLUDE_FROM_ALL)
endif()
find_path(LUABRIDGE3_INCLUDE_DIR LuaBridge/LuaBridge.h
  HINTS "${LUABRIDGE3_SOURCE_DIR}/Source" "${LUABRIDGE3_SOURCE_DIR}/source")
if(NOT LUABRIDGE3_INCLUDE_DIR)
  message(FATAL_ERROR "LuaBridge3 headers missing. See README.md for dependency setup.")
endif()
