cmake_minimum_required(VERSION 3.16)
project(mqtt-matter-bridge C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -Wextra -D_POSIX_C_SOURCE=200809L")
include(CheckIncludeFile)
check_include_file(mosquitto.h HAVE_MOSQUITTO_H)
check_include_file(libwebsockets.h HAVE_LIBWEBSOCKETS_H)
check_include_file(cjson/cJSON.h HAVE_CJSON_H)

set(EXTRA_SOURCES)
set(EXTRA_LIBS pthread)
if(HAVE_MOSQUITTO_H)
    list(APPEND EXTRA_LIBS mosquitto)
else()
    list(APPEND EXTRA_SOURCES src/compat/mosquitto_stub.c)
    include_directories(src/compat)
    message(WARNING "mosquitto.h not found; building with local compatibility stub")
endif()
if(HAVE_LIBWEBSOCKETS_H)
    list(APPEND EXTRA_LIBS websockets)
else()
    list(APPEND EXTRA_SOURCES src/compat/libwebsockets_stub.c)
    include_directories(src/compat)
    message(WARNING "libwebsockets.h not found; building with local compatibility stub")
endif()
if(HAVE_CJSON_H)
    list(APPEND EXTRA_LIBS cjson)
else()
    list(APPEND EXTRA_SOURCES src/compat/cjson_stub.c)
    include_directories(src/compat)
    message(WARNING "cjson/cJSON.h not found; building with local compatibility stub")
endif()

# Cross-compile cho Pi 3B+ (ARM 32-bit)
# Dùng: cmake -B build -DCROSS_COMPILE_PI3=ON
if(CROSS_COMPILE_PI3)
    set(CMAKE_SYSTEM_NAME Linux)
    set(CMAKE_SYSTEM_PROCESSOR arm)
    set(CMAKE_C_COMPILER arm-linux-gnueabihf-gcc)
    message(STATUS "Cross-compiling for Pi 3B+ (ARM 32-bit)")
endif()

# Cross-compile cho Pi 4B (ARM 64-bit)
# Dùng: cmake -B build -DCROSS_COMPILE_PI4=ON
if(CROSS_COMPILE_PI4)
    set(CMAKE_SYSTEM_NAME Linux)
    set(CMAKE_SYSTEM_PROCESSOR aarch64)
    set(CMAKE_C_COMPILER aarch64-linux-gnu-gcc)
    message(STATUS "Cross-compiling for Pi 4B (ARM 64-bit)")
endif()

# Include directories
include_directories(
    src/utils
    src/queue
    src/mqtt
    src/matter
    src/mapper
    src/device
)

# Source files
set(SOURCES
    src/main.c
    src/bridge.c
    src/utils/logger.c
    src/utils/config_parser.c
    src/queue/ring_buffer.c
    src/queue/message_queue.c
    src/mqtt/mqtt_client.c
    src/matter/matter_client.c
    src/mapper/mapper.c
    src/device/light_device.c
)

# Build bridge daemon
add_executable(mqtt_matter_bridge ${SOURCES})
target_link_libraries(mqtt_matter_bridge
    mosquitto
    websockets
    cjson
    pthread
)

# Build tests
enable_testing()

# Test logger
add_executable(test_logger
    tests/test_logger.c
    src/utils/logger.c
)
target_include_directories(test_logger PRIVATE src/utils)
target_link_libraries(test_logger pthread)
add_test(NAME test_logger COMMAND test_logger)

# Test config_parser
add_executable(test_config_parser
    tests/test_config_parser.c
    src/utils/config_parser.c
    src/utils/logger.c
)
target_include_directories(test_config_parser PRIVATE src/utils)
target_link_libraries(test_config_parser cjson pthread)
add_test(NAME test_config_parser COMMAND test_config_parser)

# Test ring_buffer
add_executable(test_ring_buffer
    tests/test_ring_buffer.c
    src/queue/ring_buffer.c
)
target_include_directories(test_ring_buffer PRIVATE src/queue)
add_test(NAME test_ring_buffer COMMAND test_ring_buffer)

# Test message_queue
add_executable(test_message_queue
    tests/test_message_queue.c
    src/queue/message_queue.c
    src/queue/ring_buffer.c
    src/utils/logger.c
)
target_include_directories(test_message_queue PRIVATE src/queue src/utils)
target_link_libraries(test_message_queue pthread)
add_test(NAME test_message_queue COMMAND test_message_queue)

# Test mqtt_client
add_executable(test_mqtt_client
    tests/test_mqtt_client.c
    src/mqtt/mqtt_client.c
    src/queue/message_queue.c
    src/queue/ring_buffer.c
    src/utils/logger.c
    src/utils/config_parser.c
    src/device/light_device.c
)
target_include_directories(test_mqtt_client PRIVATE
    src/mqtt src/queue src/utils src/device)
target_link_libraries(test_mqtt_client mosquitto cjson pthread)

# Test matter_client
add_executable(test_matter_client
    tests/test_matter_client.c
    src/matter/matter_client.c
    src/queue/message_queue.c
    src/queue/ring_buffer.c
    src/utils/logger.c
    src/utils/config_parser.c
)
target_include_directories(test_matter_client PRIVATE
    src/matter src/queue src/utils)
target_link_libraries(test_matter_client websockets cjson pthread)

# Test mapper
add_executable(test_mapper
    tests/test_mapper.c
    src/mapper/mapper.c
    src/utils/logger.c
    src/utils/config_parser.c
    src/queue/ring_buffer.c
)
target_include_directories(test_mapper PRIVATE

    src/mapper src/utils src/queue)
target_link_libraries(test_mapper cjson pthread)
add_test(NAME test_mapper COMMAND test_mapper)