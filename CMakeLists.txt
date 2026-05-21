cmake_minimum_required(VERSION 3.20)

project(ied_mms_server C)

set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)

set(BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(BUILD_PYTHON_BINDINGS OFF CACHE BOOL "" FORCE)
set(CONFIG_INCLUDE_GOOSE_SUPPORT OFF CACHE BOOL "" FORCE)
set(CONFIG_IEC61850_L2_GOOSE OFF CACHE BOOL "" FORCE)
set(CONFIG_IEC61850_L2_SMV OFF CACHE BOOL "" FORCE)
set(CONFIG_IEC61850_R_GOOSE OFF CACHE BOOL "" FORCE)
set(CONFIG_IEC61850_R_SMV OFF CACHE BOOL "" FORCE)
set(CONFIG_IEC61850_SNTP_CLIENT OFF CACHE BOOL "" FORCE)
set(CONFIG_IEC61850_LOG_SERVICE OFF CACHE BOOL "" FORCE)

add_subdirectory(vendor/libiec61850 libiec61850_build)

add_executable(ied_mms_server
    src/ied_mms_server.c
    generated/ref615_static_model.c
    generated/reu615_static_model.c
    generated/red615_static_model.c
)

target_include_directories(ied_mms_server PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/generated
    ${CMAKE_CURRENT_BINARY_DIR}/libiec61850_build/config
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/hal/inc
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/common/inc
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/goose
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/sampled_values
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/r_session
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/iec61850/inc
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/iec61850/inc_private
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/mms/inc
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/mms/inc_private
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/mms/iso_mms/asn1c
    ${CMAKE_CURRENT_SOURCE_DIR}/vendor/libiec61850/src/logging
)

target_link_libraries(ied_mms_server PRIVATE iec61850)
