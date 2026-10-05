#ifndef _WASM_MIGRATION_INTERNALS_H_
#define _WASM_MIGRATION_INTERNALS_H_

#include "wasm_export.h"
#include "wasm_exec_env.h"

#ifdef __cplusplus
extern "C" {
#endif

#define FNV1A_OFFSET_BASIS 2166136261U
#define FNV1A_PRIME 16777619U

#include "transport.h"
#include "protocol.h"
#include <pthread.h>

typedef struct LiveMigrationContext {
    LiveMigrationMembraneMode mode;
    bool stop_requested;
    bool active;
    bool udp_restored;
    bool flusher_started;
    bool reader_started;

    /* Lifecycle/base-state protocol and continuous event projection use
       independent ordered streams. */
    int control_fd;
    int projection_fd;

    LiveMigrationMetadata client_metadata;

    LiveMigrationMembraneMemoryTracker membrane_tracker;

    pthread_mutex_t swap_mutex;
    pthread_t flusher_thread_id;
    pthread_t reader_thread_id;

    uint8_t *active_buffer;
    uint32_t active_offset;
    uint8_t *background_buffer;
    uint32_t background_offset;

    uint32_t volatile event_counter;
    uint32_t event_flush_counter;

    wasm_exec_env_t exec_env;
} LiveMigrationContext;

extern LiveMigrationContext *global_lm_context;

LiveMigrationContext *
live_migration_context_init(wasm_exec_env_t exec_env);

void
live_migration_context_destroy(LiveMigrationContext *ctx);

typedef struct {
    LiveMigrationContext *ctx;
    int port;
} MigrationServerArgs;

void
close_projection_socket(LiveMigrationContext *ctx);

static inline uint32_t
hash_func_import(const char *module_name, const char *field_name, const char *signature)
{
    uint32_t hash = FNV1A_OFFSET_BASIS;
    const char *str_ptrs[3] = { module_name, field_name, signature };

    for (int i = 0; i < 3; i++) {
        const char *str = str_ptrs[i];
        if (str) {
            while (*str) {
                hash ^= (uint32_t)(unsigned char)(*str);
                hash *= FNV1A_PRIME;
                str++;
            }
        }
        // Hash the null terminator ('\0') as an unambiguous field separator!
        // This ensures ("a", "bc", "s") and ("ab", "c", "s") generate distinct hashes.
        hash ^= 0x00;
        hash *= FNV1A_PRIME;
    }

    return hash;
}

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_INTERNALS_H_ */
