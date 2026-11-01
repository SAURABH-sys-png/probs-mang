cmake_minimum_required(VERSION 3.16)

project(probs_mang LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_executable(probs_mang
    main.cpp
    engine/api.cpp
    engine/primary.cpp
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
