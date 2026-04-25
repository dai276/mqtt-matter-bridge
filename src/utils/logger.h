#ifndef LOGGER_H
#define LOGGER_H

#include <stdarg.h>

//Log levels — thứ tự tăng dần về độ nghiêm trọng
typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO  = 1,
    LOG_WARN  = 2,
    LOG_ERROR = 3
} log_level_t;

// Cấu hình logger — truyền vào logger_init()
typedef struct {
    log_level_t  min_level;       
    char         log_file[256];   
    int          log_to_stdout;   
} logger_config_t;

 //API

int logger_init(const logger_config_t *config);



void logger_log(log_level_t level, const char *module,
                const char *fmt, ...);


void logger_set_level(log_level_t level);


void logger_destroy(void);


//Macro
#define LOG_DBG(module, fmt, ...) \
    logger_log(LOG_DEBUG, module, fmt, ##__VA_ARGS__)

#define LOG_INF(module, fmt, ...) \
    logger_log(LOG_INFO,  module, fmt, ##__VA_ARGS__)

#define LOG_WRN(module, fmt, ...) \
    logger_log(LOG_WARN,  module, fmt, ##__VA_ARGS__)

#define LOG_ERR(module, fmt, ...) \
    logger_log(LOG_ERROR, module, fmt, ##__VA_ARGS__)

#endif /* LOGGER_H */