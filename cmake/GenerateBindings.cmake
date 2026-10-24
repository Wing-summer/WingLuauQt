# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

set(QTLUAU_BINDING_CONFIG "${PROJECT_SOURCE_DIR}/config/bindings.json" CACHE FILEPATH "Binding policy")
set(QTLUAU_GENERATED_DIR "${PROJECT_BINARY_DIR}/codegen")
file(GLOB QTLUAU_GENERATOR_INPUTS CONFIGURE_DEPENDS
  "${PROJECT_SOURCE_DIR}/python/qtluau_codegen/*.py"
  "${PROJECT_SOURCE_DIR}/config/bindings.json"
  "${PROJECT_SOURCE_DIR}/include/qtluau/*.hpp"
  "${PROJECT_SOURCE_DIR}/support/qt/*.cpp")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${QTLUAU_BINDING_CONFIG}" ${QTLUAU_GENERATOR_INPUTS})
execute_process(COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
  "${Python3_EXECUTABLE}" -m qtluau_codegen.qt_pipeline --config "${QTLUAU_BINDING_CONFIG}" --out "${QTLUAU_GENERATED_DIR}"
  RESULT_VARIABLE QTLUAU_SCAN_STATUS)
if(NOT QTLUAU_SCAN_STATUS EQUAL 0)
  message(FATAL_ERROR "Qt binding generation failed; see diagnostics above.")
endif()
execute_process(COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
  "${Python3_EXECUTABLE}" -m qtluau_codegen.generate_definitions
  --config "${QTLUAU_GENERATED_DIR}/resolved-bindings.json" --out "${QTLUAU_GENERATED_DIR}/definitions"
  RESULT_VARIABLE qtluau_definition_status)
if(NOT qtluau_definition_status EQUAL 0)
  message(FATAL_ERROR "Luau definition generation failed")
endif()
# Each discovered class becomes a translation unit; adding a class needs no source-list edit.
file(GLOB qtluau_generated_sources CONFIGURE_DEPENDS "${QTLUAU_GENERATED_DIR}/*.cpp")
target_sources(qtluau_runtime PRIVATE ${qtluau_generated_sources})
target_include_directories(qtluau_runtime PUBLIC "${QTLUAU_GENERATED_DIR}")
add_custom_target(generate_definitions
  COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
    "${Python3_EXECUTABLE}" -m qtluau_codegen.generate_definitions
    --config "${QTLUAU_GENERATED_DIR}/resolved-bindings.json" --out "${PROJECT_BINARY_DIR}/definitions"
  COMMENT "Generating Luau definitions from the resolved binding surface" VERBATIM)

# User extension inputs are tracked separately from generated translation units.
file(STRINGS "${QTLUAU_GENERATED_DIR}/extension_inputs.txt" qtluau_extension_inputs)
file(STRINGS "${QTLUAU_GENERATED_DIR}/extension_sources.txt" qtluau_extension_sources)
file(STRINGS "${QTLUAU_GENERATED_DIR}/extension_include_dirs.txt" qtluau_extension_include_dirs)
file(STRINGS "${QTLUAU_GENERATED_DIR}/extension_defines.txt" qtluau_extension_defines)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${qtluau_extension_inputs} ${qtluau_extension_sources})
target_sources(qtluau_runtime PRIVATE ${qtluau_extension_sources})
target_include_directories(qtluau_runtime PUBLIC ${qtluau_extension_include_dirs})
target_compile_definitions(qtluau_runtime PUBLIC ${qtluau_extension_defines})

file(STRINGS "${QTLUAU_GENERATED_DIR}/extension_globs.txt" qtluau_extension_globs)
foreach(pattern IN LISTS qtluau_extension_globs)
  file(GLOB_RECURSE qtluau_extension_watched CONFIGURE_DEPENDS "${pattern}")
endforeach()
