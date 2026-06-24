#include "libwebsockets.h"
#include <stdlib.h>
struct lws_context { void *user; const struct lws_protocols *protocols; };
struct lws { struct lws_context *context; };
void lws_set_log_level(int level, void *log_emit_function){ (void)level;(void)log_emit_function; }
struct lws_context *lws_create_context(const struct lws_context_creation_info *info){ struct lws_context *c=calloc(1,sizeof(*c)); if(c&&info){c->user=info->user;c->protocols=info->protocols;} return c; }
void lws_context_destroy(struct lws_context *context){ free(context); }
struct lws *lws_client_connect_via_info(const struct lws_client_connect_info *info){ if(!info) return NULL; struct lws *w=calloc(1,sizeof(*w)); if(w) w->context=info->context; if(w && info->context && info->context->protocols && info->context->protocols[0].callback) info->context->protocols[0].callback(w,LWS_CALLBACK_CLIENT_ESTABLISHED,NULL,NULL,0); return w; }
int lws_service(struct lws_context *context, int timeout_ms){ (void)context;(void)timeout_ms; return 0; }
struct lws_context *lws_get_context(struct lws *wsi){ return wsi?wsi->context:NULL; }
void *lws_context_user(struct lws_context *context){ return context?context->user:NULL; }
int lws_write(struct lws *wsi, unsigned char *buf, size_t len, int type){ (void)wsi;(void)buf;(void)type; return (int)len; }
int lws_callback_on_writable(struct lws *wsi){ (void)wsi; return 0; }
