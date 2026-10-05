#include "capabilities.h"

/* Capability Virtualization for the UDP capability class in the prototype. */

#include <stdio.h>
#include <time.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>

LiveMigrationCapabilityContext live_migration_capability_context = {
    .os_fd = -1,
    .port = 0,
};

void
live_migration_log_udp_port(uint16_t port)
{
    live_migration_capability_context.port = port;
}

void
live_migration_log_udp_fd(int fd)
{
    live_migration_capability_context.os_fd = fd;
}

/* Copies the tracked logical UDP binding into the migration metadata. */
void
live_migration_capture_udp_state(LiveMigrationMetadata *meta)
{
    clock_t time_start = clock();

    meta->active_udp_os_fd = live_migration_capability_context.os_fd;
    meta->active_udp_port = live_migration_capability_context.port;

    clock_t time_end = clock();
    double duration = ((double)(time_end - time_start)) / CLOCKS_PER_SEC;
    printf("[LM/Checkpoint] Capturing the UDP state took %f ms (fd: %i, port: %i)\n", duration * 1000.0,
           live_migration_capability_context.os_fd, live_migration_capability_context.port);
}

/* Re-creates the target-local UDP resource and updates WAMR's binding. */
bool
live_migration_restore_udp_socket(wasm_exec_env_t exec_env, int wasm_fd, uint16_t port)
{
    if (wasm_fd < 0) {
        return true; // No UDP socket was active
    }

    clock_t time_start = clock();

    // 1. Create a fresh UDP socket (the OS will give it a random available FD, e.g., 8)
    int new_sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (new_sock < 0) {
        perror("[LM/Restore] Socket creation failed");
        return false;
    }

    // 2. Allow port reuse (Critical if you are testing migrations rapidly)
    int opt = 1;
    setsockopt(new_sock, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#ifdef SO_REUSEPORT
    setsockopt(new_sock, SOL_SOCKET, SO_REUSEPORT, &opt, sizeof(opt));
#endif

    // 3. Bind it to the exact same port the WASM app is listening on
    struct sockaddr_in addr = { 0 };
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (bind(new_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("[LM/Restore] UDP bind failed");
        close(new_sock);
        return false;
    }

    clock_t time_end = clock();
    double duration = ((double)(time_end - time_start)) / CLOCKS_PER_SEC;
    printf("[LM/Restore] UDP socket rebound on port %u for logical descriptor %d. Took %f ms\n",
           port, wasm_fd, duration * 1000.0);

    live_migration_capability_context.os_fd = wasm_fd;
    live_migration_capability_context.port = port;

    // 5. Update WAMR's internal WASI FD table to point to the new host FD
    wasm_runtime_update_udp_fd(exec_env, wasm_fd, new_sock);

    return true;
}
