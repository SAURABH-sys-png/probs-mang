cmake_minimum_required(VERSION 3.16)

project(probs_mang LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(CMAKE_INSTALL_PREFIX_INITIALIZED_TO_DEFAULT)
    set(CMAKE_INSTALL_PREFIX "$ENV{HOME}/.local" CACHE PATH "Install prefix" FORCE)
endif()
include(GNUInstallDirs)

set(PROBS_MANG_COMMAND "compi" CACHE STRING "Command installed to launch the GUI")

find_package(PkgConfig REQUIRED)
pkg_check_modules(PQXX REQUIRED IMPORTED_TARGET libpqxx)
pkg_check_modules(PQ REQUIRED IMPORTED_TARGET libpq)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

option(PROBS_MANG_STATIC_PQXX "Link the static libpqxx.a when available" ON)
find_library(PQXX_STATIC_LIBRARY NAMES libpqxx.a HINTS ${PQXX_LIBRARY_DIRS})

add_executable(probs_mang
    main.cpp
    engine/api.cpp
    engine/primary.cpp
    engine/data_analysis.cpp
    database/db.cpp
)

target_include_directories(probs_mang
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${CMAKE_CURRENT_SOURCE_DIR}/include
        ${CMAKE_CURRENT_SOURCE_DIR}/engine
)

target_compile_definitions(probs_mang
    PRIVATE
        PROBS_MANG_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
        PROBS_MANG_BINARY_DIR="${CMAKE_CURRENT_BINARY_DIR}"
        PROBS_MANG_CXX_COMPILER="${CMAKE_CXX_COMPILER}"
)

if(PROBS_MANG_STATIC_PQXX AND PQXX_STATIC_LIBRARY)
    target_include_directories(probs_mang PRIVATE ${PQXX_INCLUDE_DIRS})
    target_link_libraries(probs_mang PRIVATE ${PQXX_STATIC_LIBRARY} PkgConfig::PQ)
else()
    target_link_libraries(probs_mang PRIVATE PkgConfig::PQXX)
endif()

set(PROBS_MANG_INSTALL_BACKEND
    "${CMAKE_INSTALL_FULL_LIBEXECDIR}/probs_mang/probs_mang")
set(PROBS_MANG_INSTALL_GUI "${CMAKE_INSTALL_FULL_DATADIR}/probs_mang/gui.py")

file(GENERATE
    OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/${PROBS_MANG_COMMAND}"
    CONTENT "#!/bin/sh
export PROBS_MANG_BIN=\"\${PROBS_MANG_BIN:-$<TARGET_FILE:probs_mang>}\"
exec \"${Python3_EXECUTABLE}\" \"${CMAKE_CURRENT_SOURCE_DIR}/ui/gui.py\" \"$@\"
"
    FILE_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE
                     GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE
)

file(GENERATE
    OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/install/${PROBS_MANG_COMMAND}"
    CONTENT "#!/bin/sh
export PROBS_MANG_BIN=\"\${PROBS_MANG_BIN:-${PROBS_MANG_INSTALL_BACKEND}}\"
exec \"${Python3_EXECUTABLE}\" \"${PROBS_MANG_INSTALL_GUI}\" \"$@\"
"
)

install(TARGETS probs_mang
    RUNTIME DESTINATION "${CMAKE_INSTALL_LIBEXECDIR}/probs_mang")
install(FILES ui/gui.py
    DESTINATION "${CMAKE_INSTALL_DATADIR}/probs_mang")
install(PROGRAMS "${CMAKE_CURRENT_BINARY_DIR}/install/${PROBS_MANG_COMMAND}"
    DESTINATION "${CMAKE_INSTALL_BINDIR}")
