#ifndef _WASM_MIGRATION_CAPABILITIES_H_
#define _WASM_MIGRATION_CAPABILITIES_H_

#include "wasm_export.h"
#include "wasm_exec_env.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
    int os_fd;
    uint16_t port;
} LiveMigrationCapabilityContext;

extern LiveMigrationCapabilityContext live_migration_capability_context;

void live_migration_log_udp_port(uint16_t port);
void live_migration_log_udp_fd(int fd);
void wasm_runtime_update_udp_fd(wasm_exec_env_t exec_env, int32_t wasm_fd, int32_t host_fd);

void
live_migration_capture_udp_state(LiveMigrationMetadata *meta);

bool
live_migration_restore_udp_socket(wasm_exec_env_t exec_env, int wasm_fd, uint16_t port);

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_CAPABILITIES_H_ */
