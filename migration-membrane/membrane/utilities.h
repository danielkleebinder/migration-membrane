#ifndef _WASM_MIGRATION_UTILITIES_H_
#define _WASM_MIGRATION_UTILITIES_H_

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint64_t
get_time_in_ns(void);

double
get_time_in_ms(void);

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_UTILITIES_H_ */
