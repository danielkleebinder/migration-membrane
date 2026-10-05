#ifndef _WASM_MIGRATION_MEMBRANE_H_
#define _WASM_MIGRATION_MEMBRANE_H_

#include "wasm_export.h"
#include "wasm_exec_env.h"

typedef struct LiveMigrationContext LiveMigrationContext;
struct WASMMemoryInstance;

#ifdef __cplusplus
extern "C" {
#endif

bool
wasm_live_migration_server(wasm_exec_env_t exec_env, int port);

bool
wasm_live_migration_client(wasm_exec_env_t exec_env, const char *host, int port);

void
live_migration_membrane_record_access(LiveMigrationContext *ctx, uint64 app_offset, uint64 size);

void
live_migration_membrane_reset_memory_tracker(LiveMigrationContext *ctx, struct WASMMemoryInstance *memory_inst);

void
live_migration_membrane_extract_mutations(LiveMigrationContext *ctx, struct WASMMemoryInstance *memory_inst,
                                         LiveMigrationMembraneEvent *ev);

#ifdef __cplusplus
}
#endif

#endif /* _WASM_MIGRATION_MEMBRANE_H_ */
