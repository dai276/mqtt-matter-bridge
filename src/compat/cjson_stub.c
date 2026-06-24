#define _POSIX_C_SOURCE 200809L
#include "cjson/cJSON.h"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
static const char *g_err;
static const char *skip_ws(const char *p){ while(p && isspace((unsigned char)*p)) p++; return p; }
static cJSON *new_item(int type){ cJSON *i=calloc(1,sizeof(*i)); if(i)i->type=type; return i; }
static char *parse_string_raw(const char **pp){ const char *p=skip_ws(*pp); if(*p!='\"'){g_err=p;return NULL;} p++; const char *start=p; while(*p && *p!='\"') p++; if(*p!='\"'){g_err=p;return NULL;} size_t n=(size_t)(p-start); char *s=malloc(n+1); if(!s)return NULL; memcpy(s,start,n); s[n]='\0'; *pp=p+1; return s; }
static cJSON *parse_value(const char **pp);
static cJSON *parse_object(const char **pp){ const char *p=skip_ws(*pp); if(*p!='{') return NULL; p++; cJSON *obj=new_item(cJSON_Object), *tail=NULL; p=skip_ws(p); if(*p=='}'){*pp=p+1; return obj;} while(*p){ char *key=parse_string_raw(&p); if(!key){cJSON_Delete(obj);return NULL;} p=skip_ws(p); if(*p!=':'){free(key);cJSON_Delete(obj);g_err=p;return NULL;} p++; cJSON *val=parse_value(&p); if(!val){free(key);cJSON_Delete(obj);return NULL;} val->string=key; if(tail) tail->next=val; else obj->child=val; tail=val; p=skip_ws(p); if(*p==','){p++; continue;} if(*p=='}'){*pp=p+1; return obj;} g_err=p; cJSON_Delete(obj); return NULL;} g_err=p; cJSON_Delete(obj); return NULL; }
static cJSON *parse_array(const char **pp){ const char *p=skip_ws(*pp); if(*p!='[') return NULL; p++; cJSON *arr=new_item(cJSON_Array), *tail=NULL; p=skip_ws(p); if(*p==']'){*pp=p+1; return arr;} while(*p){ cJSON *val=parse_value(&p); if(!val){cJSON_Delete(arr);return NULL;} if(tail) tail->next=val; else arr->child=val; tail=val; p=skip_ws(p); if(*p==','){p++; continue;} if(*p==']'){*pp=p+1; return arr;} g_err=p; cJSON_Delete(arr); return NULL;} g_err=p; cJSON_Delete(arr); return NULL; }
static cJSON *parse_number(const char **pp){ char *end=NULL; double d=strtod(*pp,&end); if(end==*pp){g_err=*pp;return NULL;} cJSON *n=new_item(cJSON_Number); if(!n)return NULL; n->valuedouble=d; n->valueint=(int)d; *pp=end; return n; }
static cJSON *parse_value(const char **pp){ const char *p=skip_ws(*pp); if(*p=='{') return parse_object(pp); if(*p=='[') return parse_array(pp); if(*p=='\"'){ cJSON *s=new_item(cJSON_String); if(!s)return NULL; s->valuestring=parse_string_raw(&p); if(!s->valuestring){free(s);return NULL;} *pp=p; return s; } if(strncmp(p,"true",4)==0){*pp=p+4;return new_item(cJSON_True);} if(strncmp(p,"false",5)==0){*pp=p+5;return new_item(cJSON_False);} if(strncmp(p,"null",4)==0){*pp=p+4;return new_item(cJSON_NULL);} return parse_number(pp); }
cJSON *cJSON_Parse(const char *value){ g_err=NULL; if(!value)return NULL; const char *p=value; cJSON *r=parse_value(&p); if(!r)return NULL; p=skip_ws(p); if(*p){g_err=p; cJSON_Delete(r); return NULL;} return r; }
void cJSON_Delete(cJSON *item){ while(item){ cJSON *next=item->next; cJSON_Delete(item->child); free(item->string); free(item->valuestring); free(item); item=next; } }
cJSON *cJSON_GetObjectItemCaseSensitive(const cJSON *object, const char *string){ if(!object||object->type!=cJSON_Object)return NULL; for(cJSON *c=object->child;c;c=c->next) if(c->string && strcmp(c->string,string)==0) return c; return NULL; }
int cJSON_IsString(const cJSON *item){ return item && item->type==cJSON_String; }
int cJSON_IsNumber(const cJSON *item){ return item && item->type==cJSON_Number; }
int cJSON_IsArray(const cJSON *item){ return item && item->type==cJSON_Array; }
int cJSON_IsBool(const cJSON *item){ return item && (item->type==cJSON_True || item->type==cJSON_False); }
int cJSON_IsTrue(const cJSON *item){ return item && item->type==cJSON_True; }
int cJSON_GetArraySize(const cJSON *array){ int n=0; if(!array||array->type!=cJSON_Array)return 0; for(cJSON *c=array->child;c;c=c->next)n++; return n; }
const char *cJSON_GetErrorPtr(void){ return g_err; }
