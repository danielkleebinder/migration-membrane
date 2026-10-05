#ifndef _WASM_MIGRATION_TRANSPORT_H_
#define _WASM_MIGRATION_TRANSPORT_H_

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

bool
transfer_write(int fd, const void *buf, size_t size);

bool
transfer_read(int fd, void *buf, size_t size);

void
transport_close(int *fd);

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_TRANSPORT_H_ */
