#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>

// Forward declarations for WASI BSD socket functions
int socket(int domain, int type, int protocol);
int bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen);
ssize_t recvfrom(int sockfd, void *buf, size_t len, int flags, struct sockaddr *src_addr, socklen_t *addrlen);
ssize_t sendto(int sockfd, const void *buf, size_t len, int flags, const struct sockaddr *dest_addr, socklen_t addrlen);

#define PORT 5000
#define BUFFER_SIZE 256
#define WASM_PAGE_SIZE 65536
#define DEFAULT_RAM_MB 256

int main(int argc, char *argv[]) {
    int target_mb = DEFAULT_RAM_MB;

    // 1. Read target RAM in MB from CLI argument
    if (argc > 1) {
        int parsed = atoi(argv[1]);
        if (parsed > 0) {
            target_mb = parsed;
        }
    }

    // 1 MB = 16 WASM pages (16 * 64 KB = 1024 KB = 1 MB)
    size_t target_pages = (size_t)target_mb * 16;
    size_t current_pages = __builtin_wasm_memory_size(0);

    printf("[WASM UDP Server] Initial memory: %zu pages (%zu MB)\n",
           current_pages, (current_pages * 64) / 1024);
    fflush(stdout);

    // 2. Grow linear memory to requested size
    if (current_pages < target_pages) {
        size_t pages_to_grow = target_pages - current_pages;
        printf("[WASM UDP Server] Requesting memory grow: +%zu pages (+%d MB)...\n",
               pages_to_grow, target_mb);
        fflush(stdout);

        intptr_t prev_pages = __builtin_wasm_memory_grow(0, pages_to_grow);
        if (prev_pages == -1) {
            fprintf(stderr, "[ERROR] __builtin_wasm_memory_grow failed!\n");
            fprintf(stderr, "[HINT] Compile with -Wl,--max-memory=2147483648\n");
            return -1;
        }
    }

    size_t total_pages = __builtin_wasm_memory_size(0);
    size_t total_bytes = total_pages * WASM_PAGE_SIZE;
    printf("[WASM UDP Server] Memory successfully expanded: %zu pages (%zu MB / %.2f GB)\n",
           total_pages, total_bytes / (1024 * 1024), (double)total_bytes / (1024 * 1024 * 1024));
    fflush(stdout);

    // 3. Pointer offset past low static data (64 KB offset)
    uint8_t *ram_buffer = (uint8_t *)0x10000;
    size_t buffer_size = total_bytes - 0x10000;

    // Dirty memory pages to ensure snapshot serialization during live migration
    memset(ram_buffer, 0xAB, buffer_size);
    printf("[WASM UDP Server] Dirtied %zu MB of linear memory.\n", buffer_size / (1024 * 1024));
    fflush(stdout);

    // 4. Socket Setup
    int sockfd;
    char buffer[BUFFER_SIZE];
    struct sockaddr_in servaddr, cliaddr;

    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("[WASM UDP] Socket creation failed");
        return -1;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = INADDR_ANY;
    servaddr.sin_port = htons(PORT);

    if (bind(sockfd, (const struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("[WASM UDP] Bind failed");
        close(sockfd);
        return -1;
    }

    printf("[WASM UDP Server] Listening on 0.0.0.0:%d...\n", PORT);
    fflush(stdout);

    unsigned long packet_count = 0;

    while (1) {
        socklen_t len = sizeof(cliaddr);
        ssize_t n = recvfrom(sockfd, buffer, BUFFER_SIZE - 1, 0, (struct sockaddr *)&cliaddr, &len);

        if (n < 0) {
            printf("[LM/Error] recvfrom failed with errno %d: %s\n", errno, strerror(errno));
            fflush(stdout);
        } else {
            buffer[n] = '\0';
            packet_count++;

            // Mutate memory per packet to simulate active runtime state changes
            ram_buffer[packet_count % buffer_size] = (uint8_t)(packet_count & 0xFF);

            printf("[WASM UDP Server] Recv %ld bytes (Packets: %lu, Memory: %zu MB): %s",
                   n, packet_count, total_bytes / (1024 * 1024), buffer);
            fflush(stdout);

            // --- ACK RESPONSE ---
            char ack_msg[128];
            int ack_len = snprintf(ack_msg, sizeof(ack_msg), "ACK:%s", buffer);
            sendto(sockfd, ack_msg, ack_len, 0, (struct sockaddr *)&cliaddr, len);
        }
    }

    close(sockfd);
    return 0;
}