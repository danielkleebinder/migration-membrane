#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>

/* Forward declarations for the WASI BSD socket functions used by WAMR. */
int socket(int domain, int type, int protocol);
int bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen);
ssize_t recvfrom(int sockfd, void *buf, size_t len, int flags,
                 struct sockaddr *src_addr, socklen_t *addrlen);
ssize_t sendto(int sockfd, const void *buf, size_t len, int flags,
               const struct sockaddr *dest_addr, socklen_t addrlen);

#define PORT 5000
#define MAX_UDP_PAYLOAD 65507
#define WASM_PAGE_SIZE 65536
#define DEFAULT_RAM_MB 256
#define DEFAULT_DIRTY_KB_PER_PACKET 0.0
#define BLOCK_SIZE 256

/* Static storage avoids putting a full-size UDP buffer on the WASM stack. */
static char packet_buffer[MAX_UDP_PAYLOAD + 1];

static uint64_t
parse_sequence(const char *payload, size_t length)
{
    char *end = NULL;
    unsigned long long value;

    if (length < 5 || memcmp(payload, "Seq=", 4) != 0)
        return 0;

    value = strtoull(payload + 4, &end, 10);
    if (end == payload + 4 || value == 0)
        return 0;

    return (uint64_t)value;
}

int
main(int argc, char *argv[])
{
    int target_mb = DEFAULT_RAM_MB;
    double dirty_kb_per_packet = DEFAULT_DIRTY_KB_PER_PACKET;
    size_t initial_pages;
    size_t target_pages;
    size_t total_pages;
    size_t total_bytes;
    size_t buffer_size;
    size_t block_count;
    size_t blocks_per_packet = 0;
    size_t dirty_cursor = 0;
    uint8_t *ram_buffer;
    uint64_t packet_count = 0;
    uint64_t pattern_iteration = 0;
    uint64_t state_digest = UINT64_C(14695981039346656037);
    intptr_t previous_pages;
    int sockfd;
    struct sockaddr_in servaddr;
    struct sockaddr_in cliaddr;

    setvbuf(stdout, NULL, _IONBF, 0);

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

    initial_pages = __builtin_wasm_memory_size(0);
    target_pages = (size_t)target_mb * 16;
    if (target_pages <= initial_pages) {
        fprintf(stderr,
                "[ERROR] Requested memory (%d MB) must exceed the initial WASM footprint (%zu MB).\n",
                target_mb,
                (initial_pages * WASM_PAGE_SIZE) / (1024 * 1024));
        return 2;
    }

    previous_pages = __builtin_wasm_memory_grow(0, target_pages - initial_pages);
    if (previous_pages == -1) {
        fprintf(stderr, "[ERROR] __builtin_wasm_memory_grow failed.\n");
        return 2;
    }

    total_pages = __builtin_wasm_memory_size(0);
    total_bytes = total_pages * WASM_PAGE_SIZE;
    ram_buffer = (uint8_t *)(initial_pages * WASM_PAGE_SIZE);
    buffer_size = (target_pages - initial_pages) * WASM_PAGE_SIZE;
    block_count = buffer_size / BLOCK_SIZE;

    memset(ram_buffer, 0xAB, buffer_size);

    if (dirty_kb_per_packet > 0.0) {
        size_t requested_bytes = (size_t)(dirty_kb_per_packet * 1024.0);
        blocks_per_packet = (requested_bytes + BLOCK_SIZE - 1) / BLOCK_SIZE;
        if (blocks_per_packet == 0)
            blocks_per_packet = 1;
        if (blocks_per_packet > block_count)
            blocks_per_packet = block_count;
    }

    printf("[WASM UDP Server] Memory=%zu MB | Dirty=%.2f KB/packet "
           "(%zu x %d-byte blocks)\n",
           total_bytes / (1024 * 1024),
           dirty_kb_per_packet,
           blocks_per_packet,
           BLOCK_SIZE);

    sockfd = socket(AF_INET, SOCK_DGRAM, 0);
    if (sockfd < 0) {
        perror("[WASM UDP] socket");
        return 2;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = INADDR_ANY;
    servaddr.sin_port = htons(PORT);

    if (bind(sockfd, (const struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("[WASM UDP] bind");
        close(sockfd);
        return 2;
    }

    printf("[WASM UDP Server] Listening on 0.0.0.0:%d\n", PORT);

    while (1) {
        socklen_t client_len = sizeof(cliaddr);
        ssize_t received = recvfrom(sockfd,
                                    packet_buffer,
                                    MAX_UDP_PAYLOAD,
                                    0,
                                    (struct sockaddr *)&cliaddr,
                                    &client_len);
        uint64_t sequence;
        char ack[128];
        int formatted;
        size_t ack_length;

        if (received < 0)
            continue;

        packet_buffer[received] = '\0';
        sequence = parse_sequence(packet_buffer, (size_t)received);
        if (sequence == 0)
            continue;

        packet_count++;

        if (blocks_per_packet > 0) {
            uint8_t pattern_byte;
            size_t i;

            pattern_iteration++;
            pattern_byte = (uint8_t)(pattern_iteration & 0xFF);
            for (i = 0; i < blocks_per_packet; i++) {
                memset(ram_buffer + dirty_cursor * BLOCK_SIZE,
                       pattern_byte,
                       BLOCK_SIZE);
                dirty_cursor++;
                if (dirty_cursor == block_count)
                    dirty_cursor = 0;
            }
        }
        else {
            ram_buffer[packet_count % buffer_size] = (uint8_t)(packet_count & 0xFF);
        }

        /* A compact, migrated state witness for continuity checks. */
        state_digest ^= sequence;
        state_digest *= UINT64_C(1099511628211);
        state_digest ^= packet_count;
        state_digest *= UINT64_C(1099511628211);
        state_digest ^= dirty_cursor;
        state_digest *= UINT64_C(1099511628211);

        formatted = snprintf(ack,
                             sizeof(ack),
                             "ACK|Seq=%" PRIu64 "|AppCount=%" PRIu64
                             "|State=%016" PRIx64,
                             sequence,
                             packet_count,
                             state_digest);
        if (formatted < 0)
            continue;

        ack_length = (size_t)formatted;
        if (ack_length >= sizeof(ack))
            ack_length = sizeof(ack) - 1;

        (void)sendto(sockfd,
                     ack,
                     ack_length,
                     0,
                     (struct sockaddr *)&cliaddr,
                     client_len);
    }

    close(sockfd);
    return 0;
}