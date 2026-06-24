#ifndef COMPAT_CJSON_H
#define COMPAT_CJSON_H
#include <stddef.h>
#define cJSON_False 0
#define cJSON_True 1
#define cJSON_NULL 2
#define cJSON_Number 3
#define cJSON_String 4
#define cJSON_Array 5
#define cJSON_Object 6
typedef struct cJSON { struct cJSON *next; struct cJSON *child; int type; char *string; char *valuestring; int valueint; double valuedouble; } cJSON;
cJSON *cJSON_Parse(const char *value);
void cJSON_Delete(cJSON *item);
cJSON *cJSON_GetObjectItemCaseSensitive(const cJSON *object, const char *string);
int cJSON_IsString(const cJSON *item);
int cJSON_IsNumber(const cJSON *item);
int cJSON_IsArray(const cJSON *item);
int cJSON_IsBool(const cJSON *item);
int cJSON_IsTrue(const cJSON *item);
int cJSON_GetArraySize(const cJSON *array);
const char *cJSON_GetErrorPtr(void);
#define cJSON_ArrayForEach(element, array) for(element = ((array) ? (array)->child : NULL); element != NULL; element = element->next)
#endif
