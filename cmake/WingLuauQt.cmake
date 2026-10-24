# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

include_guard(GLOBAL)
include("${CMAKE_CURRENT_LIST_DIR}/WingLuauQtPython.cmake")
set(_WINGLUAUQT_ROOT "${CMAKE_CURRENT_LIST_DIR}/..")
cmake_path(NORMAL_PATH _WINGLUAUQT_ROOT)
string(REGEX REPLACE "/+$" "" _WINGLUAUQT_ROOT "${_WINGLUAUQT_ROOT}")

# Generate at configure time so add_subdirectory always sees complete sources.
function(wingluauqt_generate)
  cmake_parse_arguments(PARSE_ARGV 0 ARG "" "CONFIG;OUTPUT_DIR;ROOT;DRIVER;DRIVER_CONFIG" "DEPENDS")
  if(ARG_UNPARSED_ARGUMENTS OR NOT ARG_CONFIG OR NOT ARG_OUTPUT_DIR OR NOT ARG_ROOT)
    message(FATAL_ERROR "wingluauqt_generate requires CONFIG, OUTPUT_DIR and ROOT")
  endif()
  wingluauqt_prepare_python()
  get_filename_component(_root "${ARG_ROOT}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
  get_filename_component(_config "${ARG_CONFIG}" ABSOLUTE BASE_DIR "${_root}")
  get_filename_component(_output "${ARG_OUTPUT_DIR}" ABSOLUTE BASE_DIR "${_root}")
  set(_command "${Python3_EXECUTABLE}" -m qtluau_codegen.project --config "${_config}" --out "${_output}" --root "${_root}")
  if(ARG_DRIVER)
    get_filename_component(_driver "${ARG_DRIVER}" ABSOLUTE BASE_DIR "${_root}")
    set(_command "${Python3_EXECUTABLE}" "${_driver}" --config "${_config}" --out "${_output}" --host "${_root}")
    if(ARG_DRIVER_CONFIG)
      get_filename_component(_driver_config "${ARG_DRIVER_CONFIG}" ABSOLUTE BASE_DIR "${_root}")
      list(APPEND _command --project "${_driver_config}")
    endif()
  endif()
  file(GLOB_RECURSE _framework_inputs CONFIGURE_DEPENDS
    "${_WINGLUAUQT_ROOT}/python/qtluau_codegen/*.py"
    "${_WINGLUAUQT_ROOT}/config/bindings.json"
    "${_WINGLUAUQT_ROOT}/include/qtluau/*.hpp"
    "${_WINGLUAUQT_ROOT}/support/*.cpp"
    "${_WINGLUAUQT_ROOT}/support/qt/*.cpp")
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${_config}" ${_driver} ${_driver_config} ${ARG_DEPENDS} ${_framework_inputs})
  if(EXISTS "${_WINGLUAUQT_ROOT}/python")
    set(_command "${CMAKE_COMMAND}" -E env "PYTHONPATH=${_WINGLUAUQT_ROOT}/python" ${_command})
  elseif(WINGLUAUQT_PYTHON_PACKAGE_ROOT)
    # Append the installed framework after this venv's dependencies, so an older
    # tsujikiri in the caller's site-packages cannot shadow the validated version.
    list(REMOVE_AT _command 0)
    set(_launcher "import runpy, sys
sys.path.append(sys.argv.pop(1))
entry = sys.argv.pop(1)
if entry == '-m':
    runpy.run_module(sys.argv.pop(1), run_name='__main__', alter_sys=True)
else:
    runpy.run_path(entry, run_name='__main__')")
    set(_command "${Python3_EXECUTABLE}" -c "${_launcher}" "${WINGLUAUQT_PYTHON_PACKAGE_ROOT}" ${_command})
  endif()
  execute_process(COMMAND ${_command} RESULT_VARIABLE _result)
  if(NOT _result EQUAL 0)
    message(FATAL_ERROR "WingLuauQt generation failed; see generator diagnostics above")
  endif()
  set(_wingluauqt_input_root "${_root}")
  include("${_output}/generation_inputs.cmake")
endfunction()
