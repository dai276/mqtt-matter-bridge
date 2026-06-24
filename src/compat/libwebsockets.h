#ifndef COMPAT_LIBWEBSOCKETS_H
#define COMPAT_LIBWEBSOCKETS_H
#include <stddef.h>
#define LWS_PRE 16
#define CONTEXT_PORT_NO_LISTEN -1
#define LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT 0
#define LWS_WRITE_TEXT 0
struct lws_context; struct lws;
enum lws_callback_reasons { LWS_CALLBACK_CLIENT_ESTABLISHED, LWS_CALLBACK_CLIENT_RECEIVE, LWS_CALLBACK_CLIENT_WRITEABLE, LWS_CALLBACK_CLIENT_CONNECTION_ERROR, LWS_CALLBACK_CLIENT_CLOSED };
struct lws_protocols { const char *name; int (*callback)(struct lws *, enum lws_callback_reasons, void *, void *, size_t); size_t per_session_data_size; size_t rx_buffer_size; int id; };
struct lws_context_creation_info { int port; const struct lws_protocols *protocols; void *user; int options; };
struct lws_client_connect_info { struct lws_context *context; const char *address; int port; const char *path; const char *host; const char *origin; const char *protocol; int ssl_connection; };
void lws_set_log_level(int level, void *log_emit_function);
struct lws_context *lws_create_context(const struct lws_context_creation_info *info);
void lws_context_destroy(struct lws_context *context);
struct lws *lws_client_connect_via_info(const struct lws_client_connect_info *info);
int lws_service(struct lws_context *context, int timeout_ms);
struct lws_context *lws_get_context(struct lws *wsi);
void *lws_context_user(struct lws_context *context);
int lws_write(struct lws *wsi, unsigned char *buf, size_t len, int type);
int lws_callback_on_writable(struct lws *wsi);
#endif
