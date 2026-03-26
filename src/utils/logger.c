#define _POSIX_C_SOURCE 200809L
#include "logger.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pthread.h>

static struct {
    log_level_t     min_level;
    int             log_to_stdout;
    FILE           *log_file;
    pthread_mutex_t mutex;
    int             initialized;
} g_logger = {
    .min_level     = LOG_INFO,
    .log_to_stdout = 1,
    .log_file      = NULL,
    .initialized   = 0
};

 // Helper — chuyển level sang string có padding
static const char *level_to_str(log_level_t level)
{
    switch (level) {
        case LOG_DEBUG: return "DEBUG";
        case LOG_INFO:  return "INFO ";
        case LOG_WARN:  return "WARN ";
        case LOG_ERROR: return "ERROR";
        default:        return "?????";
    }
}

/* ============================================================
 * API Implementation
 * ============================================================ */

int logger_init(const logger_config_t *config)
{
    if (!config) return -1;

    /* Khởi tạo mutex */
    if (pthread_mutex_init(&g_logger.mutex, NULL) != 0) {
        fprintf(stderr, "[LOGGER] Failed to init mutex\n");
        return -1;
    }

    g_logger.min_level     = config->min_level;
    g_logger.log_to_stdout = config->log_to_stdout;
    g_logger.log_file      = NULL;

    /* Mở file log nếu được cấu hình */
    if (config->log_file[0] != '\0') {
        g_logger.log_file = fopen(config->log_file, "a");
        if (!g_logger.log_file) {
            fprintf(stderr, "[LOGGER] Cannot open log file: %s\n",
                    config->log_file);
            pthread_mutex_destroy(&g_logger.mutex);
            return -1;
        }
    }

    g_logger.initialized = 1;
    return 0;
}

void logger_log(log_level_t level, const char *module,
                const char *fmt, ...)
{
    /* Chưa init hoặc dưới min_level — bỏ qua ngay */
    if (!g_logger.initialized || level < g_logger.min_level)
        return;

    /* Lấy timestamp có millisecond */
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);

    struct tm tm_info;
    localtime_r(&ts.tv_sec, &tm_info);

    char time_buf[32];
    strftime(time_buf, sizeof(time_buf), "%Y-%m-%d %H:%M:%S", &tm_info);

    /* Format message từ varargs */
    char msg_buf[512];
    va_list args;
    va_start(args, fmt);
    vsnprintf(msg_buf, sizeof(msg_buf), fmt, args);
    va_end(args);

    /* Format dòng log hoàn chỉnh */
    char log_buf[640];
    snprintf(log_buf, sizeof(log_buf),
             "[%s.%03ld] [%s] [%-12s] %s\n",
             time_buf,
             ts.tv_nsec / 1000000,   /* milliseconds */
             level_to_str(level),
             module ? module : "unknown",
             msg_buf);

    /* Lock — ghi — unlock */
    pthread_mutex_lock(&g_logger.mutex);

    if (g_logger.log_to_stdout)
        fputs(log_buf, stdout);

    if (g_logger.log_file) {
        fputs(log_buf, g_logger.log_file);
        fflush(g_logger.log_file);  /* Flush ngay để không mất log khi crash */
    }

    pthread_mutex_unlock(&g_logger.mutex);
}

void logger_set_level(log_level_t level)
{
    pthread_mutex_lock(&g_logger.mutex);
    g_logger.min_level = level;
    pthread_mutex_unlock(&g_logger.mutex);
}

void logger_destroy(void)
{
    if (!g_logger.initialized) return;

    pthread_mutex_lock(&g_logger.mutex);

    if (g_logger.log_file) {
        fflush(g_logger.log_file);
        fclose(g_logger.log_file);
        g_logger.log_file = NULL;
    }

    g_logger.initialized = 0;

    pthread_mutex_unlock(&g_logger.mutex);
    pthread_mutex_destroy(&g_logger.mutex);
}