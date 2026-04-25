#ifndef MAPPER_H
#define MAPPER_H

#include "ring_buffer.h"
#include "config_parser.h"
#include "matter_client.h"

// Khởi tạo mapper với config — gọi một lần khi startup
// Return: 0 nếu thành công, -1 nếu lỗi
int mapper_init(bridge_config_t *config);

// Dịch bridge_message sang matter_command
// Return: 0 nếu thành công, -1 nếu không tìm thấy rule
int mapper_translate(const bridge_message_t *msg,
                     matter_command_t       *cmd);

// Dọn dẹp
void mapper_destroy(void);

#endif // MAPPER_H