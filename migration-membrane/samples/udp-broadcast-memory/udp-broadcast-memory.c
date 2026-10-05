#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>

// Forward declarations for WASI BSD socket functions
int
socket(int domain, int type, int protocol);
int
bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen);
ssize_t
recvfrom(int sockfd, void *buf, size_t len, int flags, struct sockaddr *src_addr, socklen_t *addrlen);
ssize_t
sendto(int sockfd, const void *buf, size_t len, int flags, const struct sockaddr *dest_addr, socklen_t addrlen);

#define PORT 5000
#define BUFFER_SIZE 256
#define WASM_PAGE_SIZE 65536
#define DEFAULT_RAM_MB 256
#define DEFAULT_DIRTY_KB_PER_PACKET 0.0
#define BLOCK_SIZE 512

int
main(int argc, char *argv[])
{
    // Disable stdout buffering for cleaner WASI logs
    setvbuf(stdout, NULL, _IONBF, 0);

    int target_mb = DEFAULT_RAM_MB;
    double dirty_kb_per_packet = DEFAULT_DIRTY_KB_PER_PACKET;

    // 1. Read CLI arguments
    if (argc > 1) {
        int parsed_mb = atoi(argv[1]);
        if (parsed_mb > 0)
            target_mb = parsed_mb;
    }
    if (argc > 2) {
        double parsed_kb = atof(argv[2]);
        if (parsed_kb >= 0.0)
            dirty_kb_per_packet = parsed_kb;
    }

    // 2. Capture initial compiler memory size
    size_t initial_pages = __builtin_wasm_memory_size(0);
    size_t target_pages = (size_t)target_mb * 16;

    // 3. Grow linear memory to requested size
    if (initial_pages < target_pages) {
        size_t pages_to_grow = target_pages - initial_pages;
        intptr_t prev_pages = __builtin_wasm_memory_grow(0, pages_to_grow);
        if (prev_pages == -1) {
            fprintf(stderr, "[ERROR] __builtin_wasm_memory_grow failed!\n");
            return -1;
        }
    }

    size_t total_pages = __builtin_wasm_memory_size(0);
    size_t total_bytes = total_pages * WASM_PAGE_SIZE;
    printf("[WASM UDP Server] Memory: %zu MB | Dirty KB per Packet: %.2f KB (256-byte blocks)\n",
           total_bytes / (1024 * 1024), dirty_kb_per_packet);
    fflush(stdout);

    // 4. Safe pointer offset past compiler data/stack
    uint8_t *ram_buffer = (uint8_t *)(initial_pages * WASM_PAGE_SIZE);
    size_t buffer_size = (target_pages - initial_pages) * WASM_PAGE_SIZE;

    // Initial baseline dirty sweep
    memset(ram_buffer, 0xAB, buffer_size);

    size_t block_count = buffer_size / BLOCK_SIZE;
    size_t dirty_cursor = 0;

    size_t bytes_per_packet = (size_t)(dirty_kb_per_packet * 1024.0);
    size_t blocks_per_packet = bytes_per_packet / BLOCK_SIZE;
    if (dirty_kb_per_packet > 0.0 && blocks_per_packet == 0) {
        blocks_per_packet = 1;
    }

    // 5. Socket Setup
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
    uint64_t pattern_iteration = 0;

    while (1) {
        socklen_t len = sizeof(cliaddr);

        ssize_t n = recvfrom(sockfd, buffer, BUFFER_SIZE - 1, 0, (struct sockaddr *)&cliaddr, &len);

        if (n < 0) {
            continue;
        }

        buffer[n] = '\0';
        packet_count++;

        // --- MEMORY MUTATION (256-BYTE BLOCKS) ---
        if (blocks_per_packet > 0) {
            pattern_iteration++;
            uint8_t pattern_byte = (uint8_t)(pattern_iteration & 0xFF);

            // Mutate the configured number of 256-byte blocks using a rolling cursor with wrap-around
            for (size_t i = 0; i < blocks_per_packet; i++) {
                memset(ram_buffer + (dirty_cursor * BLOCK_SIZE), pattern_byte, BLOCK_SIZE);
                dirty_cursor++;
                if (dirty_cursor >= block_count) {
                    dirty_cursor = 0;
                }
            }
        }
        else {
            // Fallback single-byte mutation to maintain active state changes if 0 KB specified
            ram_buffer[packet_count % buffer_size] = (uint8_t)(packet_count & 0xFF);
        }

        // --- ACK RESPONSE ---
        char ack_msg[128];
        int ack_len = snprintf(ack_msg, sizeof(ack_msg), "ACK:%s", buffer);
        sendto(sockfd, ack_msg, ack_len, 0, (struct sockaddr *)&cliaddr, len);
    }

    close(sockfd);
    return 0;
}