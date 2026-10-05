#include <stdio.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>

// Forward declarations for WASI BSD socket functions.
// This guarantees compilation regardless of your sysroot header version.
int
socket(int domain, int type, int protocol);
int
bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen);
ssize_t
recvfrom(int sockfd, void *buf, size_t len, int flags, struct sockaddr *src_addr, socklen_t *addrlen);

// DO NOT CHANGE, MIGHT BREAK APP
#define PORT 5000
#define BUFFER_SIZE 256

int
main(void)
{
    int sockfd;
    char buffer[BUFFER_SIZE];
    struct sockaddr_in servaddr, cliaddr;

    // 1. Create UDP socket
    if ((sockfd = socket(AF_INET, SOCK_DGRAM, 0)) < 0) {
        perror("[WASM UDP] Socket creation failed");
        return -1;
    }

    memset(&servaddr, 0, sizeof(servaddr));
    servaddr.sin_family = AF_INET;
    servaddr.sin_addr.s_addr = INADDR_ANY;
    servaddr.sin_port = htons(PORT);

    // 2. Bind socket to port 5000
    if (bind(sockfd, (const struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("[WASM UDP] Bind failed");
        close(sockfd);
        return -1;
    }

    printf("[WASM UDP Server] Listening on 0.0.0.0:%d...\n", PORT);
    fflush(stdout);

    // 3. Continuous reception loop
    while (1) {
        socklen_t len = sizeof(cliaddr);
        ssize_t n = recvfrom(sockfd, buffer, BUFFER_SIZE - 1, 0, (struct sockaddr *)&cliaddr, &len);

        if (n < 0) {
            printf("[LM/Error] recvfrom failed with errno %d: %s\n", errno, strerror(errno));
            fflush(stdout);
        }
        else {
            buffer[n] = '\0';
            printf("[WASM UDP Server] Recv: %lu bytes (Port: %i, Len %i, fd: %i): %s", n, cliaddr.sin_port, len, sockfd, buffer);
            fflush(stdout);
        }
    }

    close(sockfd);
    return 0;
}