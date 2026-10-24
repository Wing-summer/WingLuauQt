# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

cmake_minimum_required(VERSION 3.24)
project(QtLuauTextEditorTests LANGUAGES CXX)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
get_filename_component(generator_root "../.." ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
set(binding_root "${CMAKE_CURRENT_BINARY_DIR}/bindings")
include("${generator_root}/cmake/WingLuauQt.cmake")
wingluauqt_generate(CONFIG bindings.json ROOT "${CMAKE_CURRENT_SOURCE_DIR}" OUTPUT_DIR "${binding_root}")
set(LUAU_SOURCE_DIR "${generator_root}/3rdparty/luau" CACHE PATH "Luau source")
set(LUABRIDGE3_SOURCE_DIR "${generator_root}/3rdparty/LuaBridge3" CACHE PATH "LuaBridge3 source")
add_subdirectory("${binding_root}" bindings-build)
add_executable(QtLuauTextEditor main.cpp)
target_compile_definitions(QtLuauTextEditor PRIVATE EDITOR_SCRIPT="${CMAKE_CURRENT_SOURCE_DIR}/editor.luau")
target_link_libraries(QtLuauTextEditor PRIVATE EditorBindings::Bindings)
EditorBindings_copy_definitions(QtLuauTextEditor)
enable_testing()
add_test(NAME text_editor_menu_responses COMMAND QtLuauTextEditor --smoke)
set_tests_properties(text_editor_menu_responses PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
