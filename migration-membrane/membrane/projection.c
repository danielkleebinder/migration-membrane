#include "projection.h"

/* Continuous State Projection: capture, transfer, replay, and convergence. */

#include "membrane.h"
#include "internals.h"
#include "utilities.h"
#include "capabilities.h"
#include "transport.h"
#include "integration.h"
#include "wasm_interp.h"
#include "wasm_exec_env.h"
#include "../interpreter/wasm_runtime.h"
#include "wasm_suspend_flags.h"
#include <stdio.h>
#include <unistd.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netdb.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

#define PROJECTION_BUFFER_SIZE (64U * 1024U * 1024U)
#define CLIENT_MEMBRANE_BUFFER_EVENTS (2U * 1024U * 1024U)

/* The prototype supports one migration session per runtime process. */
static size_t host_generated_event_count;
static uint32_t replayed_event_count;
static LiveMigrationMembraneEvent
    *client_membrane_buffer[CLIENT_MEMBRANE_BUFFER_EVENTS];
static uint32_t client_buf_head;
static uint32_t client_buf_tail;
static uint32_t client_buf_count;
static size_t client_buf_total_count;
static bool client_network_closed;
static pthread_mutex_t client_buf_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t client_buf_cond = PTHREAD_COND_INITIALIZER;

void
tear_down_live_migration(void)
{
    LiveMigrationContext *ctx = global_lm_context;

    if (!ctx)
        return;

    ctx->stop_requested = true;
    ctx->active = false;
    pthread_mutex_lock(&client_buf_mutex);
    pthread_cond_broadcast(&client_buf_cond);
    pthread_mutex_unlock(&client_buf_mutex);
    close_projection_socket(ctx);
}

void
live_migration_membrane_record_access(LiveMigrationContext *ctx, uint64 app_offset,
                                      uint64 size)
{
    if (!ctx || ctx->mode != LIVE_MIGRATION_MODE_RECORD
        || app_offset > UINT32_MAX || size > UINT32_MAX
        || ctx->membrane_tracker.count >= MAX_MEMBRANE_ACCESSES)
        return;

    ctx->membrane_tracker.records[ctx->membrane_tracker.count].app_offset =
        (uint32_t)app_offset;
    ctx->membrane_tracker.records[ctx->membrane_tracker.count].length =
        (uint32_t)size;
    ctx->membrane_tracker.count++;
}

void
live_migration_membrane_reset_memory_tracker(
    LiveMigrationContext *ctx, WASMMemoryInstance *memory_inst)
{
    (void)memory_inst;

    if (!ctx)
        return;

    ctx->membrane_tracker.count = 0;
    memset(ctx->membrane_tracker.records, 0,
           sizeof(ctx->membrane_tracker.records));
}

void
live_migration_membrane_extract_mutations(
    LiveMigrationContext *ctx, WASMMemoryInstance *memory_inst,
    LiveMigrationMembraneEvent *ev)
{
    uint32_t min_offset = UINT32_MAX;
    uint32_t max_end = 0;
    uint32_t offset;
    uint32_t length;
    int i;

    if (!ctx || !memory_inst || !ev)
        return;

    ev->memory_offset = 0;
    ev->payload_length = 0;

    for (i = 0; i < ctx->membrane_tracker.count; i++) {
        uint32_t start = ctx->membrane_tracker.records[i].app_offset;
        uint32_t record_length = ctx->membrane_tracker.records[i].length;
        uint64_t end = (uint64_t)start + record_length;

        if (start < min_offset)
            min_offset = start;
        if (end > max_end)
            max_end = end > UINT32_MAX ? UINT32_MAX : (uint32_t)end;
    }

    if (min_offset == UINT32_MAX || min_offset >= memory_inst->memory_data_size)
        return;

    offset = min_offset;
    length = max_end - min_offset;
    if (length > memory_inst->memory_data_size - offset)
        length = (uint32_t)(memory_inst->memory_data_size - offset);
    if (length > MEMBRANE_MAX_SIDE_EFFECT_BYTES)
        length = MEMBRANE_MAX_SIDE_EFFECT_BYTES;

    ev->memory_offset = offset;
    ev->payload_length = length;
    memcpy(ev->side_effect_payload, memory_inst->memory_data + offset, length);
}

static void *
membrane_flusher_thread(void *arg)
{
    LiveMigrationContext *ctx = (LiveMigrationContext *)arg;
    while (ctx->active) {
        struct timespec ts;
        ts.tv_sec = 0;
        ts.tv_nsec = 500000;
        nanosleep(&ts, NULL);

        pthread_mutex_lock(&ctx->swap_mutex);
        if (ctx->active_offset > 0) {
            uint8_t *temp_buf = ctx->active_buffer;
            size_t temp_offset = ctx->active_offset;
            uint32_t temp_event_count = ctx->event_counter;

            ctx->active_buffer = ctx->background_buffer;
            ctx->active_offset = 0;
            ctx->event_counter = 0;

            ctx->background_buffer = temp_buf;
            ctx->background_offset = temp_offset;

            pthread_mutex_unlock(&ctx->swap_mutex);

            if (!transfer_write(ctx->projection_fd, ctx->background_buffer,
                                ctx->background_offset)) {
                ctx->stop_requested = true;
                ctx->active = false;
            }
            ctx->event_flush_counter += temp_event_count;
        } else {
            pthread_mutex_unlock(&ctx->swap_mutex);
        }
    }

    pthread_mutex_lock(&ctx->swap_mutex);
    if (ctx->active_offset > 0) {
        transfer_write(ctx->projection_fd, ctx->active_buffer,
                       ctx->active_offset);
    }
    pthread_mutex_unlock(&ctx->swap_mutex);

    return NULL;
}

static void *
migration_server_thread(void *arg)
{
    MigrationServerArgs *args = (MigrationServerArgs *)arg;
    LiveMigrationContext *ctx = args->ctx;
    wasm_exec_env_t exec_env = ctx->exec_env;
    int port = args->port;
    int listen_fd = -1;
    int side_listen_fd = -1;
    struct sockaddr_in address = { 0 };
    WASMModuleInstance *module_inst;
    uint8 flag;
    bool success = false;

    wasm_runtime_free(args);

    module_inst = (WASMModuleInstance *)wasm_runtime_get_module_inst(exec_env);
    if (!module_inst || !module_inst->memories || !module_inst->memories[0])
        goto cleanup;

    listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (listen_fd < 0)
        goto cleanup;

    {
        int option = 1;
        setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &option,
                   sizeof(option));
        setsockopt(listen_fd, IPPROTO_TCP, TCP_NODELAY, &option,
                   sizeof(option));
    }

    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(port);

    if (bind(listen_fd, (struct sockaddr *)&address, sizeof(address)) < 0
        || listen(listen_fd, 1) < 0)
        goto cleanup;

    printf("[LM] Waiting for migration target on port %d...\n", port);
    ctx->control_fd = accept(listen_fd, NULL, NULL);
    if (ctx->control_fd < 0)
        goto cleanup;

    side_listen_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (side_listen_fd < 0)
        goto cleanup;

    {
        int option = 1;
        int socket_buffer_size = 4 * 1024 * 1024;
        struct sockaddr_in side_address = { 0 };

        setsockopt(side_listen_fd, SOL_SOCKET, SO_REUSEADDR, &option,
                   sizeof(option));
        setsockopt(side_listen_fd, IPPROTO_TCP, TCP_NODELAY, &option,
                   sizeof(option));
        setsockopt(side_listen_fd, SOL_SOCKET, SO_SNDBUF,
                   &socket_buffer_size, sizeof(socket_buffer_size));

        side_address.sin_family = AF_INET;
        side_address.sin_addr.s_addr = INADDR_ANY;
        side_address.sin_port = htons(port + 1);

        if (bind(side_listen_fd, (struct sockaddr *)&side_address,
                 sizeof(side_address)) < 0
            || listen(side_listen_fd, 1) < 0)
            goto cleanup;
    }

    flag = LM_EOF_START;
    if (!transfer_write(ctx->control_fd, &flag, sizeof(flag)))
        goto cleanup;

    ctx->projection_fd = accept(side_listen_fd, NULL, NULL);
    if (ctx->projection_fd < 0)
        goto cleanup;

    {
        int option = 1;
        setsockopt(ctx->projection_fd, IPPROTO_TCP, TCP_NODELAY, &option,
                   sizeof(option));
    }

    close(side_listen_fd);
    side_listen_fd = -1;

    ctx->active_buffer = (uint8_t *)malloc(PROJECTION_BUFFER_SIZE);
    ctx->background_buffer = (uint8_t *)malloc(PROJECTION_BUFFER_SIZE);
    if (!ctx->active_buffer || !ctx->background_buffer)
        goto cleanup;

    ctx->active = true;
    host_generated_event_count = 0;
    if (pthread_create(&ctx->flusher_thread_id, NULL,
                       membrane_flusher_thread, ctx)
        != 0) {
        ctx->active = false;
        goto cleanup;
    }
    ctx->flusher_started = true;

    /*
     * The interpreter captures the memfd-backed linear-memory snapshot and
     * serializes the execution frames at a safe instruction boundary.
     */
    exec_env->live_migrating = true;
    exec_env->live_migration_sync_stack = true;
    while (exec_env->live_migration_sync_stack && !ctx->stop_requested)
        usleep(1000);
    if (ctx->stop_requested)
        goto cleanup;

    exec_env->live_migration_sync = true;

    {
        uint32 magic = LM_DUMP_MAGIC;
        uint32 version = LM_DUMP_VERSION;
        uint32 stack_size =
            (uint32)((uint8 *)exec_env->wasm_stack.top
                     - (uint8 *)exec_env->wasm_stack.bottom);
        uintptr_t old_stack_bottom =
            (uintptr_t)exec_env->wasm_stack.bottom;
        uint32 global_data_size = module_inst->global_data_size;
        uint32 memory_data_size =
            exec_env->live_migration_linear_memory_snapshot_size;
        uint32 cur_frame_offset =
            exec_env->serialized_frame_stream.current_frame_offset;
        uint32 frame_count = exec_env->serialized_frame_stream.count;

        if (!transfer_write(ctx->control_fd, &magic, sizeof(magic))
            || !transfer_write(ctx->control_fd, &version, sizeof(version))
            || !transfer_write(ctx->control_fd, &stack_size,
                               sizeof(stack_size))
            || !transfer_write(ctx->control_fd, &old_stack_bottom,
                               sizeof(old_stack_bottom))
            || !transfer_write(ctx->control_fd, exec_env->wasm_stack.bottom,
                               stack_size)
            || !transfer_write(ctx->control_fd, &global_data_size,
                               sizeof(global_data_size))
            || !transfer_write(ctx->control_fd, module_inst->global_data,
                               global_data_size))
            goto cleanup;

        /*
         * Recording begins before the interpreter is released. Events now
         * describe every host interaction that occurs after the base snapshot.
         */
        ctx->mode = LIVE_MIGRATION_MODE_RECORD;
        exec_env->live_migration_sync = false;

        if ((memory_data_size > 0
             && !exec_env->live_migration_linear_memory_snapshot)
            || !transfer_write(ctx->control_fd, &memory_data_size,
                               sizeof(memory_data_size))
            || !transfer_write(
                ctx->control_fd,
                exec_env->live_migration_linear_memory_snapshot,
                memory_data_size)
            || !transfer_write(ctx->control_fd, &cur_frame_offset,
                               sizeof(cur_frame_offset))
            || !transfer_write(ctx->control_fd, &frame_count,
                               sizeof(frame_count))
            || !transfer_write(
                ctx->control_fd,
                exec_env->serialized_frame_stream.buffer,
                exec_env->serialized_frame_stream.offset))
            goto cleanup;
    }

    flag = LM_EOF_INITIAL;
    if (!transfer_write(ctx->control_fd, &flag, sizeof(flag)))
        goto cleanup;

    live_migration_capture_udp_state(&ctx->client_metadata);
    if (!transfer_write(ctx->control_fd, &ctx->client_metadata,
                        sizeof(ctx->client_metadata)))
        goto cleanup;

    if (!transfer_read(ctx->control_fd, &flag, sizeof(flag))
        || flag != LM_EOF_RECONSTRUCT)
        goto cleanup;

    flag = LM_EOF_COMPLETE_SERVER;
    if (!transfer_write(ctx->control_fd, &flag, sizeof(flag))
        || !transfer_read(ctx->control_fd, &flag, sizeof(flag))
        || flag != LM_EOF_COMPLETE_CLIENT)
        goto cleanup;

    /*
     * The target reports replay progress on the projection channel. Once the
     * lag is small, stop producing effects on the source and flush the final
     * continuation before closing the channel.
     */
    {
        uint32_t last_acknowledged_event = 0;
        const uint32_t convergence_threshold = 250;
        const double maximum_convergence_time_ms = 20000.0;
        double convergence_start = get_time_in_ms();

        usleep(10000);
        while (!ctx->stop_requested) {
            uint32_t acknowledgement;
            ssize_t received =
                recv(ctx->projection_fd, &acknowledgement,
                     sizeof(acknowledgement), MSG_DONTWAIT);
            uint32_t lag;

            if (received == sizeof(acknowledgement))
                last_acknowledged_event = acknowledgement;
            else if (received < 0 && errno != EAGAIN && errno != EWOULDBLOCK
                     && errno != EINTR)
                goto cleanup;

            lag = host_generated_event_count - last_acknowledged_event;
            if (lag <= convergence_threshold)
                break;
            if (get_time_in_ms() - convergence_start
                > maximum_convergence_time_ms)
                break;

            usleep(500);
        }
    }

    ctx->mode = LIVE_MIGRATION_MODE_DISABLED;
    exec_env->live_migration_complete = true;
    WASM_SUSPEND_FLAGS_FETCH_OR(exec_env->suspend_flags,
                                WASM_SUSPEND_FLAG_TERMINATE);

    ctx->active = false;
    pthread_join(ctx->flusher_thread_id, NULL);
    ctx->flusher_started = false;

    success = true;
    printf("[LM] Migration server transmitted %zu projection events.\n",
           host_generated_event_count);

cleanup:
    ctx->mode = LIVE_MIGRATION_MODE_DISABLED;
    exec_env->live_migration_sync = false;
    ctx->active = false;

    if (ctx->flusher_started) {
        /* Abort a blocked projection write on failure before joining. */
        close_projection_socket(ctx);
        pthread_join(ctx->flusher_thread_id, NULL);
        ctx->flusher_started = false;
    }

    close_projection_socket(ctx);
    transport_close(&ctx->control_fd);
    if (side_listen_fd >= 0)
        close(side_listen_fd);
    if (listen_fd >= 0)
        close(listen_fd);

    if (!success)
        printf("[LM] Migration server aborted.\n");

    if (global_lm_context == ctx)
        global_lm_context = NULL;
    live_migration_context_destroy(ctx);
    return NULL;
}

bool
live_migration_server(wasm_exec_env_t exec_env, int port)
{
    pthread_t tid;

    if (global_lm_context)
        return false;

    LiveMigrationContext *ctx = live_migration_context_init(exec_env);
    if (!ctx) return false;
    global_lm_context = ctx;

    MigrationServerArgs *args = wasm_runtime_malloc(sizeof(MigrationServerArgs));
    if (!args) {
        global_lm_context = NULL;
        live_migration_context_destroy(ctx);
        return false;
    }
    args->ctx = ctx;
    args->port = port;
    if (pthread_create(&tid, NULL, migration_server_thread, args) != 0) {
        wasm_runtime_free(args);
        global_lm_context = NULL;
        live_migration_context_destroy(ctx);
        return false;
    }
    pthread_detach(tid);
    return true;
}

static void *
membrane_reader_worker(void *arg)
{
    LiveMigrationContext *ctx = (LiveMigrationContext *)arg;
    int fd = ctx->projection_fd;

    while (true) {
        LiveMigrationMembraneEvent header;

        if (!transfer_read(fd, &header, sizeof(LiveMigrationMembraneEvent))) {
            pthread_mutex_lock(&client_buf_mutex);
            client_network_closed = true;
            pthread_cond_signal(&client_buf_cond);
            pthread_mutex_unlock(&client_buf_mutex);
            break;
        }

        if (header.payload_length > MEMBRANE_MAX_SIDE_EFFECT_BYTES) {
            printf("[LM/Transport] ERROR: Event payload size %u exceeds maximum!\n", header.payload_length);
            pthread_mutex_lock(&client_buf_mutex);
            client_network_closed = true;
            pthread_cond_signal(&client_buf_cond);
            pthread_mutex_unlock(&client_buf_mutex);
            break;
        }

        size_t total_size = sizeof(LiveMigrationMembraneEvent) + header.payload_length;
        LiveMigrationMembraneEvent *ev = (LiveMigrationMembraneEvent *)malloc(total_size);
        if (!ev) {
            printf("[LM/Transport] ERROR: Failed to allocate memory for event!\n");
            pthread_mutex_lock(&client_buf_mutex);
            client_network_closed = true;
            pthread_cond_signal(&client_buf_cond);
            pthread_mutex_unlock(&client_buf_mutex);
            break;
        }

        memcpy(ev, &header, sizeof(LiveMigrationMembraneEvent));

        if (header.payload_length > 0) {
            if (!transfer_read(fd, ev->side_effect_payload, header.payload_length)) {
                printf("[LM/Transport] ERROR: Failed to read event payload!\n");
                free(ev);
                pthread_mutex_lock(&client_buf_mutex);
                client_network_closed = true;
                pthread_cond_signal(&client_buf_cond);
                pthread_mutex_unlock(&client_buf_mutex);
                break;
            }
        }

        client_buf_total_count++;

        pthread_mutex_lock(&client_buf_mutex);
        while (client_buf_count >= CLIENT_MEMBRANE_BUFFER_EVENTS
               && !ctx->stop_requested) {
            // Wait for space instead of dropping events
            pthread_cond_wait(&client_buf_cond, &client_buf_mutex);
        }

        if (ctx->stop_requested) {
            free(ev);
            pthread_mutex_unlock(&client_buf_mutex);
            break;
        }

        client_membrane_buffer[client_buf_head] = ev;
        client_buf_head = (client_buf_head + 1) % CLIENT_MEMBRANE_BUFFER_EVENTS;
        client_buf_count++;
        pthread_cond_signal(&client_buf_cond);
        pthread_mutex_unlock(&client_buf_mutex);
    }

    return NULL;
}

bool
live_migration_client(wasm_exec_env_t exec_env, const char *host, int port)
{
    struct sockaddr_in server_address = { 0 };
    struct sockaddr_in projection_address = { 0 };
    struct hostent *server;
    WASMModuleInstance *module_inst;
    LiveMigrationContext *ctx;
    uint8 flag;

    if (global_lm_context)
        return false;

    ctx = live_migration_context_init(exec_env);
    if (!ctx)
        return false;
    global_lm_context = ctx;

    module_inst =
        (WASMModuleInstance *)wasm_runtime_get_module_inst(exec_env);
    if (!module_inst)
        goto fail;

    server = gethostbyname(host);
    if (!server)
        goto fail;

    ctx->control_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (ctx->control_fd < 0)
        goto fail;

    server_address.sin_family = AF_INET;
    server_address.sin_port = htons(port);
    memcpy(&server_address.sin_addr.s_addr, server->h_addr,
           server->h_length);
    if (connect(ctx->control_fd, (struct sockaddr *)&server_address,
                sizeof(server_address))
        < 0)
        goto fail;

    if (!transfer_read(ctx->control_fd, &flag, sizeof(flag))
        || flag != LM_EOF_START)
        goto fail;

    ctx->projection_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (ctx->projection_fd < 0)
        goto fail;

    projection_address.sin_family = AF_INET;
    projection_address.sin_port = htons(port + 1);
    memcpy(&projection_address.sin_addr.s_addr, server->h_addr,
           server->h_length);
    if (connect(ctx->projection_fd,
                (struct sockaddr *)&projection_address,
                sizeof(projection_address))
        < 0)
        goto fail;

    {
        int option = 1;
        setsockopt(ctx->projection_fd, IPPROTO_TCP, TCP_NODELAY, &option,
                   sizeof(option));
    }

    pthread_mutex_lock(&client_buf_mutex);
    while (client_buf_count > 0) {
        free(client_membrane_buffer[client_buf_tail]);
        client_buf_tail =
            (client_buf_tail + 1) % CLIENT_MEMBRANE_BUFFER_EVENTS;
        client_buf_count--;
    }
    client_buf_head = 0;
    client_buf_tail = 0;
    client_buf_total_count = 0;
    client_network_closed = false;
    replayed_event_count = 0;
    pthread_mutex_unlock(&client_buf_mutex);

    if (pthread_create(&ctx->reader_thread_id, NULL,
                       membrane_reader_worker, ctx)
        != 0)
        goto fail;
    ctx->reader_started = true;

    if (!restore_state(exec_env, ctx->control_fd))
        goto fail;

    if (!transfer_read(ctx->control_fd, &flag, sizeof(flag))
        || flag != LM_EOF_INITIAL
        || !transfer_read(ctx->control_fd, &ctx->client_metadata,
                          sizeof(ctx->client_metadata)))
        goto fail;

    flag = LM_EOF_RECONSTRUCT;
    if (!transfer_write(ctx->control_fd, &flag, sizeof(flag)))
        goto fail;

    ctx->mode = LIVE_MIGRATION_MODE_REPLAY;

    if (!transfer_read(ctx->control_fd, &flag, sizeof(flag))
        || flag != LM_EOF_COMPLETE_SERVER)
        goto fail;

    flag = LM_EOF_COMPLETE_CLIENT;
    if (!transfer_write(ctx->control_fd, &flag, sizeof(flag)))
        goto fail;

    transport_close(&ctx->control_fd);
    return true;

fail:
    ctx->stop_requested = true;
    close_projection_socket(ctx);
    if (ctx->reader_started) {
        pthread_mutex_lock(&client_buf_mutex);
        pthread_cond_broadcast(&client_buf_cond);
        pthread_mutex_unlock(&client_buf_mutex);
        pthread_join(ctx->reader_thread_id, NULL);
        ctx->reader_started = false;
    }

    pthread_mutex_lock(&client_buf_mutex);
    while (client_buf_count > 0) {
        free(client_membrane_buffer[client_buf_tail]);
        client_buf_tail =
            (client_buf_tail + 1) % CLIENT_MEMBRANE_BUFFER_EVENTS;
        client_buf_count--;
    }
    pthread_mutex_unlock(&client_buf_mutex);

    transport_close(&ctx->control_fd);
    if (global_lm_context == ctx)
        global_lm_context = NULL;
    live_migration_context_destroy(ctx);
    return false;
}

bool
live_migration_fetch_membrane_event(LiveMigrationContext *ctx, WASMExecEnv *exec_env,
                                    LiveMigrationMembraneEvent **ev)
{
    size_t replayed_total;

    if (!ctx || !ev || ctx->mode != LIVE_MIGRATION_MODE_REPLAY) {
        return false;
    }

    pthread_mutex_lock(&client_buf_mutex);

    while (client_buf_count == 0 && !client_network_closed
           && !ctx->stop_requested) {
        pthread_cond_wait(&client_buf_cond, &client_buf_mutex);
    }

    if (client_buf_count > 0) {
        *ev = client_membrane_buffer[client_buf_tail];
        client_buf_tail = (client_buf_tail + 1) % CLIENT_MEMBRANE_BUFFER_EVENTS;
        client_buf_count--;

        pthread_cond_signal(&client_buf_cond); // Signal reader that space is available
        pthread_mutex_unlock(&client_buf_mutex);

        replayed_event_count++;
        if (replayed_event_count % 10 == 0 && ctx->projection_fd >= 0)
            send(ctx->projection_fd, &replayed_event_count,
                 sizeof(replayed_event_count), MSG_DONTWAIT);
        return true;
    }

    pthread_mutex_unlock(&client_buf_mutex);
    close_projection_socket(ctx);
    if (ctx->reader_started) {
        pthread_join(ctx->reader_thread_id, NULL);
        ctx->reader_started = false;
    }

    if (!ctx->udp_restored && ctx->client_metadata.active_udp_os_fd >= 0) {
        printf("[LM/Restore] Restore UDP socket connection (fd: %i, %f ms)\n", ctx->client_metadata.active_udp_os_fd,
               get_time_in_ms());
        ctx->udp_restored = live_migration_restore_udp_socket(
            exec_env, ctx->client_metadata.active_udp_os_fd, ctx->client_metadata.active_udp_port);

        if (!ctx->udp_restored) {
            printf("[LM/Restore] ERROR: Cannot restore UDP socket.\n");
        }
    }

    replayed_total = client_buf_total_count;
    ctx->mode = LIVE_MIGRATION_MODE_DISABLED;
    printf("[LM/Restore] Read %zu membrane events\n", replayed_total);
    printf("[LM/Restore] Live migration restored at %f ms\n", get_time_in_ms());

    if (global_lm_context == ctx)
        global_lm_context = NULL;
    live_migration_context_destroy(ctx);

    return false;
}

bool
live_migration_write_membrane_event(LiveMigrationContext *ctx, WASMExecEnv *exec_env,
                                    const LiveMigrationMembraneEvent *ev)
{
    size_t event_size;

    (void)exec_env;

    if (!ctx || !ev || ctx->stop_requested
        || ctx->mode != LIVE_MIGRATION_MODE_RECORD
        || ctx->projection_fd < 0 || !ctx->active_buffer) {
        return false;
    }

    if (ev->payload_length > MEMBRANE_MAX_SIDE_EFFECT_BYTES)
        return false;

    event_size = sizeof(LiveMigrationMembraneEvent) + ev->payload_length;
    pthread_mutex_lock(&ctx->swap_mutex);

    if (event_size > PROJECTION_BUFFER_SIZE - ctx->active_offset) {
        pthread_mutex_unlock(&ctx->swap_mutex);
        printf("[LM/Checkpoint] CRITICAL: Double-buffer full! Increase size or flush faster.\n");
        return false;
    }

    memcpy(ctx->active_buffer + ctx->active_offset, ev, event_size);
    ctx->active_offset += event_size;
    ctx->event_counter++;
    host_generated_event_count++;

    pthread_mutex_unlock(&ctx->swap_mutex);

    return true;
}
