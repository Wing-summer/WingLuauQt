# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

include_guard(GLOBAL)
set(WINGLUAUQT_PYTHON_ENV "${CMAKE_BINARY_DIR}/.wingluauqt-venv" CACHE PATH
  "Local Python environment used when the selected interpreter lacks generator dependencies")
option(WINGLUAUQT_BOOTSTRAP_PYTHON "Automatically prepare local Python generation dependencies" ON)

function(wingluauqt_prepare_python)
  cmake_parse_arguments(PARSE_ARGV 0 ARG "DEV" "" "")
  set(_manifest "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../pyproject.toml")
  set(_bootstrap "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/../python/qtluau_codegen/bootstrap.py")
  if(NOT EXISTS "${_bootstrap}")
    set(_bootstrap "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/bootstrap.py")
  endif()
  cmake_path(NORMAL_PATH _manifest)
  cmake_path(NORMAL_PATH _bootstrap)
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${_manifest}" "${_bootstrap}")
  file(STRINGS "${_manifest}" _python_requirement REGEX "^requires-python[ ]*=")
  string(REGEX MATCH "[0-9]+\\.[0-9]+" _python_minimum "${_python_requirement}")
  if(NOT _python_minimum)
    message(FATAL_ERROR "Cannot read the Python requirement from ${_manifest}")
  endif()
  find_package(Python3 ${_python_minimum} REQUIRED COMPONENTS Interpreter)
  # Preserve access to an installed framework when switching to a managed venv.
  execute_process(COMMAND "${Python3_EXECUTABLE}" -c
    "import pathlib, qtluau_codegen; print(pathlib.Path(qtluau_codegen.__file__).resolve().parent.parent)"
    RESULT_VARIABLE _package_status OUTPUT_VARIABLE _package_root
    OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
  if(_package_status EQUAL 0)
    set(WINGLUAUQT_PYTHON_PACKAGE_ROOT "${_package_root}" PARENT_SCOPE)
  endif()
  get_filename_component(_env "${WINGLUAUQT_PYTHON_ENV}" ABSOLUTE BASE_DIR "${CMAKE_BINARY_DIR}")
  set(_arguments --manifest "${_manifest}" --environment "${_env}")
  if(ARG_DEV)
    list(APPEND _arguments --dev)
  endif()
  if(NOT WINGLUAUQT_BOOTSTRAP_PYTHON)
    list(APPEND _arguments --no-install)
  endif()
  execute_process(COMMAND "${Python3_EXECUTABLE}" "${_bootstrap}" ${_arguments}
    RESULT_VARIABLE _status OUTPUT_VARIABLE _python OUTPUT_STRIP_TRAILING_WHITESPACE)
  if(NOT _status EQUAL 0)
    message(FATAL_ERROR "Could not prepare generator dependencies from ${_manifest}; see diagnostics above.")
  endif()
  message(STATUS "WingLuauQt Python: ${_python}")
  set(Python3_EXECUTABLE "${_python}" PARENT_SCOPE)
endfunction()
