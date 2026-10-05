#include "transport.h"
#include <stdio.h>
#include <errno.h>
#include <sys/socket.h>
#include <unistd.h>

bool
transfer_write(int fd, const void *buf, size_t size)
{
    if (fd < 0) {
        return false;
    }

    const uint8_t *p = (const uint8_t *)buf;
    while (size > 0) {
        ssize_t res = send(fd, p, size, 0);
        if (res <= 0) {
            if (errno == EINTR)
                continue;
            printf("[LM/Transport] ERROR: send result %zd, errno %i\n", res, errno);
            return false;
        }
        p += res;
        size -= (size_t)res;
    }
    return true;
}

bool
transfer_read(int fd, void *buf, size_t size)
{
    if (fd < 0) {
        return false;
    }

    uint8_t *p = (uint8_t *)buf;
    while (size > 0) {
        ssize_t res = recv(fd, p, size, 0);
        if (res <= 0) {
            if (errno == EINTR)
                continue;
            return false;
        }
        p += res;
        size -= (size_t)res;
    }
    return true;
}

void
transport_close(int *fd)
{
    if (fd && *fd >= 0) {
        close(*fd);
        *fd = -1;
    }
}
