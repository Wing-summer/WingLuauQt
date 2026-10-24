# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

cmake_minimum_required(VERSION 3.24)
project(WingLuauQt VERSION 0.2.0 LANGUAGES CXX)

option(QTLUAU_BUILD_TESTS "Build runtime and generation tests" ON)
list(APPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
include(Dependencies)
add_library(qtluau_runtime STATIC
  support/execute_luau.cpp
  support/module_registry.cpp)
include(GenerateBindings)
file(GLOB qtluau_support_sources CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/support/qt/*.cpp")
target_sources(qtluau_runtime PRIVATE ${qtluau_support_sources})
set_target_properties(qtluau_runtime PROPERTIES AUTOMOC ON)
add_library(WingLuauQt::Runtime ALIAS qtluau_runtime)
target_compile_features(qtluau_runtime PUBLIC cxx_std_17)
target_include_directories(qtluau_runtime
  PUBLIC "${PROJECT_SOURCE_DIR}/include" "${LUABRIDGE3_INCLUDE_DIR}")
target_link_libraries(qtluau_runtime PUBLIC Qt6::Core Qt6::Gui Qt6::Widgets Qt6::UiTools Luau.VM Luau.Compiler Threads::Threads)
if(MSVC)
  target_compile_options(qtluau_runtime PRIVATE /W4 /permissive-)
else()
  target_compile_options(qtluau_runtime PRIVATE -Wall -Wextra -Wpedantic)
endif()
if(QTLUAU_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()
