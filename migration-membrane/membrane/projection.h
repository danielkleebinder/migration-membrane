#ifndef _WASM_MIGRATION_PROJECTION_H_
#define _WASM_MIGRATION_PROJECTION_H_

#include "internals.h"
#include "transport.h"
#include "integration.h"
#include <time.h>

void
tear_down_live_migration(void);

bool
live_migration_server(wasm_exec_env_t exec_env, int port);

bool
live_migration_client(wasm_exec_env_t exec_env, const char *host, int port);

bool
live_migration_fetch_membrane_event(LiveMigrationContext *ctx, WASMExecEnv *exec_env, LiveMigrationMembraneEvent **ev);

bool
live_migration_write_membrane_event(LiveMigrationContext *ctx,
                                    WASMExecEnv *exec_env,
                                    const LiveMigrationMembraneEvent *ev);

#endif /* _WASM_MIGRATION_PROJECTION_H_ */
