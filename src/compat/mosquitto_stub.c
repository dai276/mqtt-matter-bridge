#include "mosquitto.h"
#include <stdlib.h>
struct mosquitto { void *userdata; void (*connect_cb)(struct mosquitto *, void *, int); void (*disconnect_cb)(struct mosquitto *, void *, int); };
struct mosquitto *mosquitto_new(const char *id, bool clean_session, void *userdata){ (void)id;(void)clean_session; struct mosquitto *m=calloc(1,sizeof(*m)); if(m)m->userdata=userdata; return m; }
void mosquitto_destroy(struct mosquitto *mosq){ free(mosq); }
int mosquitto_lib_init(void){ return MOSQ_ERR_SUCCESS; }
int mosquitto_lib_cleanup(void){ return MOSQ_ERR_SUCCESS; }
void mosquitto_connect_callback_set(struct mosquitto *mosq, void (*cb)(struct mosquitto *, void *, int)){ if(mosq) mosq->connect_cb=cb; }
void mosquitto_disconnect_callback_set(struct mosquitto *mosq, void (*cb)(struct mosquitto *, void *, int)){ if(mosq) mosq->disconnect_cb=cb; }
void mosquitto_message_callback_set(struct mosquitto *mosq, void (*cb)(struct mosquitto *, void *, const struct mosquitto_message *)){ (void)mosq;(void)cb; }
int mosquitto_subscribe(struct mosquitto *mosq, int *mid, const char *sub, int qos){ (void)mosq;(void)mid;(void)sub;(void)qos; return MOSQ_ERR_SUCCESS; }
int mosquitto_connect(struct mosquitto *mosq, const char *host, int port, int keepalive){ (void)host;(void)port;(void)keepalive; if(mosq&&mosq->connect_cb) mosq->connect_cb(mosq, mosq->userdata, 0); return MOSQ_ERR_SUCCESS; }
int mosquitto_loop(struct mosquitto *mosq, int timeout, int max_packets){ (void)mosq;(void)timeout;(void)max_packets; return MOSQ_ERR_SUCCESS; }
int mosquitto_reconnect(struct mosquitto *mosq){ return mosquitto_connect(mosq, NULL, 0, 0); }
int mosquitto_disconnect(struct mosquitto *mosq){ if(mosq&&mosq->disconnect_cb) mosq->disconnect_cb(mosq, mosq->userdata, 0); return MOSQ_ERR_SUCCESS; }
int mosquitto_publish(struct mosquitto *mosq, int *mid, const char *topic, int payloadlen, const void *payload, int qos, bool retain){ (void)mosq;(void)mid;(void)topic;(void)payloadlen;(void)payload;(void)qos;(void)retain; return MOSQ_ERR_SUCCESS; }
const char *mosquitto_strerror(int mosq_errno){ (void)mosq_errno; return "compat mosquitto stub"; }
