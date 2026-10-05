#define _POSIX_C_SOURCE 199309L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#include <wasi/api.h>

#define PRINT_INTERVAL_MS 1

/* Stored in WebAssembly linear memory and preserved by migration. */
static uint64_t sequence = 1;

int main(void)
{
    const struct timespec delay = {
        .tv_sec = 0,
        .tv_nsec = PRINT_INTERVAL_MS * 1000000L,
    };

    /* Make every line an immediately observable fd_write effect. */
    setvbuf(stdout, NULL, _IONBF, 0);

    for (;;) {
        uint32_t random_value;

        if (__wasi_random_get((uint8_t *)&random_value,
                              sizeof(random_value)) != __WASI_ERRNO_SUCCESS) {
            fputs("random_get failed\n", stderr);
            return 1;
        }

        static uint64_t checksum = 1469598103934665603ULL;

        /* After random_get: */
        checksum ^= sequence;
        checksum *= 1099511628211ULL;
        checksum ^= random_value;
        checksum *= 1099511628211ULL;

        printf("SEQ=%" PRIu64 " RANDOM=%08" PRIx32 " CHECKSUM=%016" PRIx64 "\n",sequence++, random_value, checksum);
        fflush(stdout);

        nanosleep(&delay, NULL);
    }
}