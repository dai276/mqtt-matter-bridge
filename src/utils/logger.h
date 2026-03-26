#ifndef LOGGER_H
#define LOGGER_H

#include <stdarg.h>

/* ============================================================
 * Log levels — thứ tự tăng dần về độ nghiêm trọng
 * ============================================================ */
typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO  = 1,
    LOG_WARN  = 2,
    LOG_ERROR = 3
} log_level_t;

/* ============================================================
 * Cấu hình logger — truyền vào logger_init()
 * ============================================================ */
typedef struct {
    log_level_t  min_level;       /* Chỉ log message >= min_level     */
    char         log_file[256];   /* Đường dẫn file log, "" = không ghi file */
    int          log_to_stdout;   /* 1 = in ra terminal, 0 = không    */
} logger_config_t;

/* ============================================================
 * API
 * ============================================================ */

/**
 * logger_init - Khởi tạo logger, gọi một lần khi startup
 * @config: con trỏ đến cấu hình logger
 * Return: 0 nếu thành công, -1 nếu lỗi
 */
int logger_init(const logger_config_t *config);

/**
 * logger_log - Hàm core ghi log (dùng qua macro bên dưới)
 * @level:  mức độ của message
 * @module: tên module gọi log (tối đa 12 ký tự)
 * @fmt:    format string kiểu printf
 */
void logger_log(log_level_t level, const char *module,
                const char *fmt, ...);

/**
 * logger_set_level - Thay đổi min_level lúc runtime
 * @level: level mới
 */
void logger_set_level(log_level_t level);

/**
 * logger_destroy - Dọn dẹp, gọi khi shutdown
 */
void logger_destroy(void);

/* ============================================================
 * Macro tiện lợi — dùng trong code hàng ngày
 * ============================================================ */
#define LOG_DBG(module, fmt, ...) \
    logger_log(LOG_DEBUG, module, fmt, ##__VA_ARGS__)

#define LOG_INF(module, fmt, ...) \
    logger_log(LOG_INFO,  module, fmt, ##__VA_ARGS__)

#define LOG_WRN(module, fmt, ...) \
    logger_log(LOG_WARN,  module, fmt, ##__VA_ARGS__)

#define LOG_ERR(module, fmt, ...) \
    logger_log(LOG_ERROR, module, fmt, ##__VA_ARGS__)

#endif /* LOGGER_H */