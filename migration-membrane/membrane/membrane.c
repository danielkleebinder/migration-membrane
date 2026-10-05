#include "membrane.h"

/* Public Migration Membrane facade and per-handover context ownership. */

#include "projection.h"
#include "internals.h"
#include "transport.h"
#include <stdlib.h>
#include <string.h>
#include <pthread.h>
#include <unistd.h>
#include <sys/socket.h>

LiveMigrationContext *global_lm_context = NULL;

LiveMigrationContext *
live_migration_context_init(wasm_exec_env_t exec_env)
{
    LiveMigrationContext *ctx = (LiveMigrationContext *)malloc(sizeof(LiveMigrationContext));
    if (!ctx)
        return NULL;

    memset(ctx, 0, sizeof(LiveMigrationContext));
    ctx->exec_env = exec_env;
    ctx->control_fd = -1;
    ctx->projection_fd = -1;
    ctx->mode = LIVE_MIGRATION_MODE_DISABLED;

    pthread_mutex_init(&ctx->swap_mutex, NULL);
    // Note: buffers are allocated in projection.c or whenever needed
    return ctx;
}

void
live_migration_context_destroy(LiveMigrationContext *ctx)
{
    if (!ctx)
        return;

    transport_close(&ctx->control_fd);
    transport_close(&ctx->projection_fd);

    if (ctx->active_buffer)
        free(ctx->active_buffer);
    if (ctx->background_buffer)
        free(ctx->background_buffer);

    pthread_mutex_destroy(&ctx->swap_mutex);
    free(ctx);
}

void
close_projection_socket(LiveMigrationContext *ctx)
{
    if (ctx && ctx->projection_fd >= 0) {
        shutdown(ctx->projection_fd, SHUT_RDWR);
        transport_close(&ctx->projection_fd);
    }
}

bool
wasm_live_migration_server(wasm_exec_env_t exec_env, int port)
{
    return live_migration_server(exec_env, port);
}

bool
wasm_live_migration_client(wasm_exec_env_t exec_env, const char *host, int port)
{
    return live_migration_client(exec_env, host, port);
}
