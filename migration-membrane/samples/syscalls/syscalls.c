#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <time.h>
#include <sched.h>
#include <string.h>

// For WASI getentropy/random
#if __has_include(<sys/random.h>)
#include <sys/random.h>
#endif

#define WASM_PAGE_SIZE (64 * 1024ULL)

// --- SYSCALL TYPES ---
#define SYSCALL_YIELD 0   // Modifies 0 bytes
#define SYSCALL_TIME 1    // Modifies sizeof(struct timespec)
#define SYSCALL_ENTROPY 2 // Modifies N bytes directly via host RNG (Membrane payload tracking)

__attribute__((import_module("wasi_snapshot_preview1"), import_name("random_get"))) extern uint16_t
raw_wasi_random_get(void *buf, size_t buf_len);

void
print_usage(const char *prog_name)
{
    printf("Usage: %s [TARGET_MB] [DIRTY_MB_PER_SEC] [SYSCALLS_PER_SEC] [SYSCALL_TYPE] [SYSCALL_MOD_BYTES]\n",
           prog_name);
    printf("  SYSCALL_TYPE: 0 = yield, 1 = clock_gettime, 2 = getentropy\n");
    printf("  Example: %s 256 50.0 1000 2 128\n", prog_name);
}

int
main(int argc, char **argv)
{
    // --- DEFAULT PARAMETERS ---
    uint64_t target_mb = 256ULL;
    double dirty_mb_per_sec = 50.0;
    uint64_t step_ms = 5ULL;
    uint64_t syscalls_per_sec = 0; // Configurable syscall injection rate
    int syscall_type = SYSCALL_YIELD;
    size_t syscall_mod_bytes = 0;

    // --- PARSE ARGUMENTS ---
    if (argc > 1)
        target_mb = strtoull(argv[1], NULL, 10);
    if (argc > 2)
        dirty_mb_per_sec = strtod(argv[2], NULL);
    if (argc > 3)
        syscalls_per_sec = strtoull(argv[3], NULL, 10);
    if (argc > 4)
        syscall_type = atoi(argv[4]);
    if (argc > 5)
        syscall_mod_bytes = strtoull(argv[5], NULL, 10);

    uint64_t target_bytes = target_mb * 1024ULL * 1024ULL;
    uint64_t target_pages = target_bytes / WASM_PAGE_SIZE;

    setvbuf(stdout, NULL, _IONBF, 0);
    printf("[WASM] Config: %llu MB | %.2f MB/s | %llu Syscalls/s (Type: %d, Modifying: %zu bytes)\n",
           (unsigned long long)target_mb, dirty_mb_per_sec, (unsigned long long)syscalls_per_sec, syscall_type,
           syscall_mod_bytes);

    // 1. Grow WASM linear memory
    size_t current_pages = __builtin_wasm_memory_size(0);
    if (current_pages < target_pages) {
        size_t pages_to_grow = target_pages - current_pages;
        if (__builtin_wasm_memory_grow(0, pages_to_grow) == -1) {
            fprintf(stderr, "[ERROR] Failed to grow WASM linear memory!\n");
            return 1;
        }
    }

    size_t total_pages = __builtin_wasm_memory_size(0);
    size_t total_bytes = total_pages * WASM_PAGE_SIZE;

    // 2. Setup Buffers
    uint64_t *ram_buffer = (uint64_t *)0x10000; // Start at 64 KB offset
    size_t element_count = (total_bytes - 0x10000) / sizeof(uint64_t);

    volatile char *raw_byte_view = (volatile char *)ram_buffer;
    size_t last_idx = total_bytes - 0x10000 - 1;

    // Leave room based on the requested payload size (or a safe max like 4096)
    size_t safety_headroom = syscall_mod_bytes > 512 ? syscall_mod_bytes : 512;

    // Position syscall_buf safely away from the absolute end of memory
    char *syscall_buf = (char *)&raw_byte_view[last_idx - safety_headroom];

    // 3. Initial baseline write sweep
    printf("[WASM] Initializing physical memory backing...\n");
    for (size_t i = 0; i < element_count; i++) {
        ram_buffer[i] = 0xAAAAAAAAAAAAAAAAULL;
    }

    // 4. Rate Calculation
    double bytes_per_sec = dirty_mb_per_sec * 1024.0 * 1024.0;
    double ticks_per_sec = 1000.0 / (double)step_ms;
    double bytes_per_tick = bytes_per_sec / ticks_per_sec;
    size_t elements_per_tick = (size_t)(bytes_per_tick / sizeof(uint64_t));
    if (elements_per_tick == 0)
        elements_per_tick = 1;

    double syscalls_per_tick = (double)syscalls_per_sec / ticks_per_sec;
    double syscall_accumulator = 0.0;

    printf("[WASM] Entering execution loop (using bypass)...\n");

    uint64_t iteration = 0;
    size_t cursor = 0;

    while (true) {
        iteration++;

        // --- 1. MEMORY DIRTYING PHASE ---
        uint64_t pattern = 0x5555555555555555ULL ^ (iteration * 0x1010101010101010ULL);
        size_t end_cursor = cursor + elements_per_tick;
        if (end_cursor > element_count)
            end_cursor = element_count;

        for (size_t i = cursor; i < end_cursor; i++) {
            ram_buffer[i] = pattern;
        }

        cursor = end_cursor;
        if (cursor >= element_count)
            cursor = 0;

        raw_byte_view[0] = 'S';
        raw_byte_view[last_idx / 2] = 'M';
        raw_byte_view[last_idx] = 'E';

        // --- 2. SYSCALL INJECTION PHASE ---
        syscall_accumulator += syscalls_per_tick;
        uint64_t syscalls_to_execute = (uint64_t)syscall_accumulator;
        syscall_accumulator -= syscalls_to_execute;

        // NEW: Record start time
        struct timespec syscall_start, syscall_end;
        clock_gettime(CLOCK_MONOTONIC, &syscall_start);

        for (uint64_t s = 0; s < syscalls_to_execute; s++) {
            struct timespec ts;
            switch (syscall_type) {
                case SYSCALL_YIELD:
                    sched_yield();
                    break;
                case SYSCALL_TIME:
                    clock_gettime(CLOCK_REALTIME, &ts);
                    if (syscall_mod_bytes > 0) {
                        size_t cpy_size = syscall_mod_bytes < sizeof(ts) ? syscall_mod_bytes : sizeof(ts);
                        memcpy(syscall_buf, &ts, cpy_size);
                    }
                    break;
                case SYSCALL_ENTROPY:
                    // Forces the WASI runtime to write directly into linear memory from the host,
                    // testing the Membrane's ability to intercept and log buffer mutations.
                    if (syscall_mod_bytes > 0) {
                        raw_wasi_random_get(syscall_buf, syscall_mod_bytes);
                    }
                    else {
                        char dev_null_buf[8];
                        raw_wasi_random_get(dev_null_buf, 8);
                    }
                    break;
            }
        }

        // NEW: Record end time and calculate duration in nanoseconds
        clock_gettime(CLOCK_MONOTONIC, &syscall_end);

        long long elapsed_ns =
            (syscall_end.tv_sec - syscall_start.tv_sec) * 1000000000LL + (syscall_end.tv_nsec - syscall_start.tv_nsec);
        // Convert to milliseconds or microseconds for readability
        double elapsed_us = (double)elapsed_ns / 1000.0;

        // --- 3. LOGGING & SLEEP ---
        if (iteration % (uint64_t)ticks_per_sec == 0) {
            bool integrity_ok =
                (raw_byte_view[0] == 'S' && raw_byte_view[last_idx / 2] == 'M' && raw_byte_view[last_idx] == 'E');

            // NEW: Added syscalls executed and execution time to the log output
            printf("[WASM] Tick %llu | Syscalls: %llu (%.2f µs) | Integrity: %s\n", (unsigned long long)iteration,
                   (unsigned long long)syscalls_to_execute, elapsed_us, integrity_ok ? "OK" : "CORRUPTED!");
        }

        usleep(step_ms * 1000);
    }

    return 0;
}