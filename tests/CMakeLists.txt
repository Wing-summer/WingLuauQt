# Copyright (c) 2026, wingsummer
# SPDX-License-Identifier: BSD-3-Clause
# See LICENSE in the project root for license information.

# Compile fixture policies ahead of time; the test executable never parses policy JSON.
set(qtluau_profiles "${CMAKE_CURRENT_BINARY_DIR}/profiles")
file(GLOB qtluau_profile_policies CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/*_config.json")
set(qtluau_profile_sources)
set(qtluau_profile_includes "#include \"profiles.hpp\"\n#include \"static_registration.hpp\"\n")
set(qtluau_profile_register "void registerTestBindings(lua_State *L, QAnyStringView name) {\n")
set(qtluau_profile_roots "QStringList testAllowedUiRoots(QAnyStringView name) {\n")
foreach(policy IN LISTS qtluau_profile_policies)
  get_filename_component(profile "${policy}" NAME_WE)
  set(profile_dir "${qtluau_profiles}/${profile}")
  execute_process(COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
    "${Python3_EXECUTABLE}" -m qtluau_codegen.registration_codegen --config "${policy}" --out "${profile_dir}"
    --namespace "qtluau::test_profiles::${profile}" RESULT_VARIABLE profile_status)
  if(NOT profile_status EQUAL 0)
    message(FATAL_ERROR "Failed to generate static fixture ${profile}")
  endif()
  set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${policy}")
  file(GLOB profile_native_sources CONFIGURE_DEPENDS "${profile_dir}/qt_auto_*.cpp")
  list(APPEND qtluau_profile_sources "${profile_dir}/static_common.cpp" "${profile_dir}/static_widgets.cpp" ${profile_native_sources})
  string(APPEND qtluau_profile_includes "#include \"${profile}/static_registration.hpp\"\n")
  string(APPEND qtluau_profile_register "if (name == QAnyStringView(u\"${profile}\")) { qtluau::test_profiles::${profile}::registerCommonBindings(L); qtluau::test_profiles::${profile}::registerQtBindings(L); return; }\n")
  string(APPEND qtluau_profile_roots "if (name == QAnyStringView(u\"${profile}\")) { return qtluau::test_profiles::${profile}::allowedUiRoots(); }\n")
endforeach()
file(WRITE "${qtluau_profiles}/profiles.hpp" "#ifndef WINGLUAUQT_TEST_PROFILES_HPP\n#define WINGLUAUQT_TEST_PROFILES_HPP\n#include \"qtluau/bindings.hpp\"\nvoid registerTestBindings(lua_State*, QAnyStringView);\nQStringList testAllowedUiRoots(QAnyStringView);\n#endif\n")
file(WRITE "${qtluau_profiles}/profiles.cpp" "${qtluau_profile_includes}${qtluau_profile_register}qtluau::registerCommonBindings(L); qtluau::registerQtBindings(L); }\n${qtluau_profile_roots}return qtluau::allowedUiRoots(); }\n")

add_executable(QtLuauRuntimeTests main.cpp "${qtluau_profiles}/profiles.cpp" ${qtluau_profile_sources})
target_include_directories(QtLuauRuntimeTests PRIVATE "${qtluau_profiles}")
target_link_libraries(QtLuauRuntimeTests PRIVATE WingLuauQt::Runtime)
target_compile_definitions(QtLuauRuntimeTests PRIVATE
  QTLUAU_DEFAULT_TEST_SCRIPT="${CMAKE_CURRENT_SOURCE_DIR}/integration.luau")
add_executable(QtLuauValueCodecTests value_codecs.cpp)
target_link_libraries(QtLuauValueCodecTests PRIVATE WingLuauQt::Runtime)
add_executable(QtLuauDefinitionTests definition_syntax.cpp)
target_link_libraries(QtLuauDefinitionTests PRIVATE Luau.Analysis)

function(qtluau_runtime_test name script)
  set(options)
  set(oneValueArgs CONFIG)
  cmake_parse_arguments(TEST "${options}" "${oneValueArgs}" "" ${ARGN})
  set(args "--script=${CMAKE_CURRENT_SOURCE_DIR}/${script}")
  if(TEST_CONFIG)
    list(APPEND args "--profile=${TEST_CONFIG}")
  endif()
  add_test(NAME ${name} COMMAND QtLuauRuntimeTests ${args})
  set_tests_properties(${name} PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen" WORKING_DIRECTORY "${PROJECT_SOURCE_DIR}")
endfunction()
function(qtluau_python_test name script)
  add_test(NAME ${name} COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
    "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/python/${script}.py" ${ARGN})
endfunction()

add_test(NAME typed_container_codecs COMMAND QtLuauValueCodecTests)
set_tests_properties(typed_container_codecs PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
qtluau_runtime_test(runtime_integration integration.luau)
qtluau_runtime_test(runtime_receiver_validation receiver_validation.luau)
qtluau_runtime_test(runtime_value_conversion value_conversion.luau CONFIG value_conversion_config)
qtluau_runtime_test(runtime_type_registry_aliases type_aliases.luau CONFIG type_aliases_config)
qtluau_runtime_test(runtime_generated_widgets generated_widgets.luau)
qtluau_runtime_test(runtime_common_capabilities capabilities.luau CONFIG capabilities_config)
qtluau_runtime_test(runtime_all_widgets all_widgets.luau CONFIG all_widgets_config)
qtluau_runtime_test(runtime_member_exclusion member_exclusion.luau CONFIG member_exclusion_config)
qtluau_runtime_test(runtime_class_exclusion class_exclusion.luau CONFIG class_exclusion_config)
qtluau_runtime_test(runtime_default_ctor_exclusion default_ctor_exclusion.luau CONFIG default_ctor_exclusion_config)
qtluau_runtime_test(runtime_selection_boundary selection.luau CONFIG selection_config)
qtluau_runtime_test(runtime_ui_file_loader ui_file.luau CONFIG ui_file_config)
qtluau_runtime_test(runtime_configurable_aliases aliases.luau CONFIG alias_config)

add_test(NAME definition_generator COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
  "${Python3_EXECUTABLE}" -m qtluau_codegen.generate_definitions
  --config "${QTLUAU_GENERATED_DIR}/resolved-bindings.json" --out "${PROJECT_BINARY_DIR}/definitions")
add_test(NAME definition_luau_syntax COMMAND QtLuauDefinitionTests
  "${PROJECT_BINARY_DIR}/definitions/common.d.luau" "${PROJECT_BINARY_DIR}/definitions/qt.d.luau"
  "${PROJECT_BINARY_DIR}/definitions/qtluau.d.luau")
add_test(NAME definition_luau_usage COMMAND QtLuauDefinitionTests
  "${PROJECT_BINARY_DIR}/definitions/qtluau.d.luau" "--probe=${CMAKE_CURRENT_SOURCE_DIR}/definition_usage.luau")
set_tests_properties(definition_luau_syntax definition_luau_usage PROPERTIES DEPENDS definition_generator)
qtluau_python_test(qt_discovery_pipeline test_qt_pipeline)
qtluau_python_test(luau_luabridge_header_order test_luau_header_order --root "${PROJECT_SOURCE_DIR}")
foreach(fixture IN ITEMS definition_variadics member_exclusions class_exclusions selection_boundary default_ctor_exclusion)
  if(fixture STREQUAL "definition_variadics")
    set(policy variadic)
  elseif(fixture STREQUAL "selection_boundary")
    set(policy selection)
  elseif(fixture STREQUAL "default_ctor_exclusion")
    set(policy default_ctor_exclusion)
  elseif(fixture STREQUAL "member_exclusions")
    set(policy member_exclusion)
  else()
    set(policy class_exclusion)
  endif()
  qtluau_python_test(${fixture} test_${fixture} --generator qtluau_codegen.generate_definitions
    --config "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/${policy}_config.json" --out "${PROJECT_BINARY_DIR}/${policy}-definitions")
endforeach()
find_program(QTLUAU_CLANGXX_EXECUTABLE NAMES clang++)
if(QTLUAU_CLANGXX_EXECUTABLE)
  qtluau_python_test(header_scanner_fixture test_header_scan --scanner qtluau_codegen.header_scan
    --fixtures "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/headers" --clang "${QTLUAU_CLANGXX_EXECUTABLE}"
    --definition-checker "$<TARGET_FILE:QtLuauDefinitionTests>")
endif()
add_test(NAME configurable_alias_definition COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
  "${Python3_EXECUTABLE}" -m qtluau_codegen.generate_definitions --config "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/alias_config.json"
  --out "${PROJECT_BINARY_DIR}/alias-definitions")
add_test(NAME python_strict COMMAND "${Python3_EXECUTABLE}" -m pyright --project "${PROJECT_SOURCE_DIR}/pyrightconfig.json")

# Exercise the same extension pipeline consumers use, including moc output compilation.
set(qtluau_extension_fixture "${CMAKE_CURRENT_BINARY_DIR}/extensions")
execute_process(COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
  "${Python3_EXECUTABLE}" -m qtluau_codegen.qt_pipeline
  --config "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/extensions/bindings.json" --out "${qtluau_extension_fixture}"
  RESULT_VARIABLE qtluau_extension_status)
if(NOT qtluau_extension_status EQUAL 0)
  message(FATAL_ERROR "Extension fixture generation failed")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/extensions/api.hpp"
  "${CMAKE_CURRENT_SOURCE_DIR}/fixtures/extensions/bindings.json")
file(GLOB qtluau_extension_fixture_sources CONFIGURE_DEPENDS "${qtluau_extension_fixture}/qt_ext_*.cpp")
add_executable(QtLuauExtensionTests extension_runtime.cpp ${qtluau_extension_fixture_sources})
target_include_directories(QtLuauExtensionTests PRIVATE "${qtluau_extension_fixture}")
target_link_libraries(QtLuauExtensionTests PRIVATE WingLuauQt::Runtime)
add_test(NAME extension_private_slots_runtime COMMAND QtLuauExtensionTests)
set_tests_properties(extension_private_slots_runtime PROPERTIES ENVIRONMENT "QT_QPA_PLATFORM=offscreen")
add_test(NAME extension_definitions COMMAND "${CMAKE_COMMAND}" -E env "PYTHONPATH=${PROJECT_SOURCE_DIR}/python"
  "${Python3_EXECUTABLE}" -m qtluau_codegen.generate_definitions
  --config "${qtluau_extension_fixture}/resolved-bindings.json" --out "${qtluau_extension_fixture}/definitions")
add_test(NAME extension_definition_syntax COMMAND QtLuauDefinitionTests "${qtluau_extension_fixture}/definitions/qtluau.d.luau")
set_tests_properties(extension_definition_syntax PROPERTIES DEPENDS extension_definitions)
qtluau_python_test(extension_generation_policy test_extensions)
add_test(NAME extension_definition_usage COMMAND QtLuauDefinitionTests
  "${qtluau_extension_fixture}/definitions/qtluau.d.luau" "--probe=${CMAKE_CURRENT_SOURCE_DIR}/extension_usage.luau")
set_tests_properties(extension_definition_usage PROPERTIES DEPENDS extension_definitions)
qtluau_python_test(static_project_export test_project --definition-checker "$<TARGET_FILE:QtLuauDefinitionTests>")

add_executable(WingLuauQtModuleTests modules.cpp)
target_link_libraries(WingLuauQtModuleTests PRIVATE WingLuauQt::Runtime)
add_test(NAME generic_module_registry COMMAND WingLuauQtModuleTests)

qtluau_python_test(api_baseline_and_naming test_api_policy)
qtluau_python_test(wrapper_declaration_contract test_wrapper_contract)
