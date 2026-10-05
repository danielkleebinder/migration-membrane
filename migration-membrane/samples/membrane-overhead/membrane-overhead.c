#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sched.h>

#define ITERATIONS 1000
#define CHUNK_SIZE (64 * 1024) // 64 KB heap chunks

// ============================================================================
// 1. Memory Growth & Page Dirtying (Triggers memory.grow / sbrk & heap traps)
// ============================================================================
void bench_memory_operations(int iter) {
    char *ptr = (char *)malloc(CHUNK_SIZE);
    if (ptr != NULL) {
        for (size_t i = 0; i < CHUNK_SIZE; i += 4096) {
            ptr[i] = (char)(iter & 0xFF);
        }
        free(ptr);
    }
}

// ============================================================================
// 2. Stream I/O Write (Triggers WASI fd_write)
// ============================================================================
void bench_stream_io_write(int iter) {
    char buf[64];
    int len = snprintf(buf, sizeof(buf), "[BENCH/IO] Iteration: %d\n", iter);
    write(STDOUT_FILENO, buf, len);
}

// ============================================================================
// 3. Clock & Timing (Triggers WASI clock_time_get)
// ============================================================================
void bench_clock_get(int iter) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    if (ts.tv_nsec == 999999999) {
        printf("Unreachable: %d\n", iter);
    }
}

// ============================================================================
// 4. Randomness / Entropy (Triggers WASI random_get)
// ============================================================================
void bench_random_get(int iter) {
    unsigned char entropy_buf[16];
    getentropy(entropy_buf, sizeof(entropy_buf));
    if (entropy_buf[0] == 0xFF && entropy_buf[15] == 0xFF) {
        printf("Unreachable: %d\n", iter);
    }
}

// ============================================================================
// 6. File Descriptor Metadata (Triggers WASI fd_fdstat_get / fd_filestat_get)
// ============================================================================
void bench_fd_stat(int iter) {
    struct stat st;
    // Query metadata of standard output. This traps to the host runtime.
    fstat(STDOUT_FILENO, &st);

    // Prevent compiler optimization
    if (st.st_size == -1 && iter < 0) {
        printf("Unreachable: %d\n", iter);
    }
}

// ============================================================================
// 7. File Seeking (Triggers WASI fd_seek)
// ============================================================================
void bench_fd_seek(int iter) {
    // Seeking on stdout (which is a pipe/tty) will return an error (ESPIPE)
    // but it will successfully traverse the WASI boundary and Membrane interceptor.
    off_t pos = lseek(STDOUT_FILENO, 0, SEEK_CUR);
    if (pos == 999999 && iter < 0) {
        printf("Unreachable: %d\n", iter);
    }
}

// ============================================================================
// 8. Scheduler Yield (Triggers WASI sched_yield)
// ============================================================================
void bench_sched_yield(int iter) {
    // Explicitly yields the thread execution. Very lightweight WASI call.
    sched_yield();
}

// ============================================================================
// 9. Polling / Blocking (Triggers WASI poll_oneoff)
// ============================================================================
void bench_poll_oneoff(int iter) {
    // Sleeps for 1 millisecond. Maps to WASI's event multiplexing / polling mechanism.
    usleep(1 * 1000);
}

// ============================================================================
// 10. Path Resolution (Triggers WASI path_filestat_get)
// ============================================================================
void bench_path_resolution(int iter) {
    // Checks existence of a path, forcing the WASM runtime to translate
    // string pointers across the sandbox boundary. Fails fast with ENOENT.
    int res = access("/stateless_dummy_path_for_benchmarking", F_OK);
    if (res == 9999 && iter < 0) {
        printf("Unreachable: %d\n", iter);
    }
}

// ============================================================================
// 11. Descriptor Syncing (Triggers WASI fd_sync)
// ============================================================================
void bench_fd_sync(int iter) {
    // Syncs file state. On stdout (tty/pipe), it fails fast (EINVAL),
    // but tests the WASI boundary perfectly without actual disk I/O.
    int res = fsync(STDOUT_FILENO);
    if (res == 9999 && iter < 0) {
        printf("Unreachable: %d\n", iter);
    }
}

// ============================================================================
// 5. Pure Compute Baseline (0 Syscalls)
// ============================================================================
unsigned int bench_pure_compute(unsigned int seed) {
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}

// ============================================================================
// Main Execution Loop
// ============================================================================
int main(int argc, char **argv) {
    int iterations = ITERATIONS;
    if (argc > 1) {
        iterations = atoi(argv[1]);
    }

    printf("=== Starting WASI Syscall Microbenchmark (%d iterations) ===\n", iterations);

    // Warmup phase
    unsigned int state = 0xACE1u;

    for (int i = 0; i < iterations; i++) {
        // Core WASI Memory/IO
        bench_memory_operations(i);
        bench_stream_io_write(i);

        // Ephemeral state WASI calls
        bench_clock_get(i);
        bench_random_get(i);

        // Filesystem/Descriptor WASI calls
        bench_fd_stat(i);
        bench_fd_seek(i);
        bench_path_resolution(i);
        bench_fd_sync(i);

        // Concurrency/Control WASI calls
        bench_sched_yield(i);
        bench_poll_oneoff(i);

        // Pure ALU baseline
        state = bench_pure_compute(state);
    }

    printf("=== WASI Syscall Microbenchmark Completed ===\n");
    return 0;
}