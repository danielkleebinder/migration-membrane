#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <unistd.h>
#include <time.h>
#include <sched.h> // For sched_yield()

// --- CONFIGURABLE WORKLOAD PARAMETERS ---
#define TARGET_MB 256ULL      // Total WASM memory size
#define DIRTY_MB_PER_SEC 50.0 // Desired dirty rate in MB/s (floating point)
#define STEP_MS 5ULL          // Step interval in milliseconds

#define TARGET_BYTES (TARGET_MB * 1024ULL * 1024ULL)
#define WASM_PAGE_SIZE (64 * 1024ULL)
#define TARGET_PAGES (TARGET_BYTES / WASM_PAGE_SIZE)

int
main(void)
{
    // Disable stdout buffering so WASI streams don't hold internal lock states across migration
    setvbuf(stdout, NULL, _IONBF, 0);

    printf("[WASM] Current WASM memory size: %zu pages (%zu MB)\n", __builtin_wasm_memory_size(0),
           (__builtin_wasm_memory_size(0) * 64) / 1024);

    // 1. Grow WASM linear memory to TARGET_MB
    size_t current_pages = __builtin_wasm_memory_size(0);
    if (current_pages < TARGET_PAGES) {
        size_t pages_to_grow = TARGET_PAGES - current_pages;
        printf("[WASM] Requesting memory grow of %zu pages (+%zu MB)...\n", pages_to_grow, (pages_to_grow * 64) / 1024);

        intptr_t prev_pages = __builtin_wasm_memory_grow(0, pages_to_grow);
        if (prev_pages == -1) {
            fprintf(stderr, "[ERROR] Failed to grow WASM linear memory!\n");
            return 1;
        }
    }

    size_t total_pages = __builtin_wasm_memory_size(0);
    size_t total_bytes = total_pages * WASM_PAGE_SIZE;
    printf("[WASM] Memory grown! Total size: %zu pages (%zu MB / %.2f GB)\n", total_pages, total_bytes / (1024 * 1024),
           (double)total_bytes / (1024 * 1024 * 1024));

    // 2. Define a 64-bit pointer over the grown linear memory
    uint64_t *ram_buffer = (uint64_t *)0x10000; // Start at 64 KB offset
    size_t element_count = (total_bytes - 0x10000) / sizeof(uint64_t);

    // 3. Initial baseline write sweep
    printf("[WASM] Initializing physical memory backing...\n");
    for (size_t i = 0; i < element_count; i++) {
        ram_buffer[i] = 0xAAAAAAAAAAAAAAAAULL;
    }

    volatile char *raw_byte_view = (volatile char *)ram_buffer;
    size_t last_idx = total_bytes - 0x10000 - 1;
    raw_byte_view[0] = 'S';
    raw_byte_view[last_idx / 2] = 'M';
    raw_byte_view[last_idx] = 'E';

    // 4. Rate Calculation for Step Intervals
    double bytes_per_sec = DIRTY_MB_PER_SEC * 1024.0 * 1024.0;
    double bytes_per_tick = bytes_per_sec / (1000.0 / (double)STEP_MS);
    size_t elements_per_tick = (size_t)(bytes_per_tick / sizeof(uint64_t));
    if (elements_per_tick == 0)
        elements_per_tick = 1;

    printf("[WASM] Target dirty rate: %.2f MB/s | Step size: %llu ms | Bytes per step: %.2f KB\n",
           (double)DIRTY_MB_PER_SEC, (unsigned long long)STEP_MS, bytes_per_tick / 1024.0);
    printf("[WASM] Entering rate-limited dirtying loop...\n");

    uint64_t iteration = 0;
    size_t cursor = 0;

    while (true) {
        iteration++;
        uint64_t pattern = 0x5555555555555555ULL ^ (iteration * 0x1010101010101010ULL);

        size_t end_cursor = cursor + elements_per_tick;
        if (end_cursor > element_count) {
            end_cursor = element_count;
        }

        // Perform the rate-limited write chunk
        for (size_t i = cursor; i < end_cursor; i++) {
            ram_buffer[i] = pattern;
        }

        cursor = end_cursor;
        if (cursor >= element_count) {
            cursor = 0;
        }

        // Re-apply boundary markers
        raw_byte_view[0] = 'S';
        raw_byte_view[last_idx / 2] = 'M';
        raw_byte_view[last_idx] = 'E';

        // --- WASI SYSCALL ANCHOR FOR IRIS MEMBRANE ---
        // Forces a WASI system call on every step to guarantee the membrane records
        // sequence checkpoints and keeps WASM local registers aligned across network migration.
        sched_yield();

        // Periodic logging and boundary verification (~every 1 second)
        if (iteration % (1000 / STEP_MS) == 0) {
            bool integrity_ok =
                (raw_byte_view[0] == 'S' && raw_byte_view[last_idx / 2] == 'M' && raw_byte_view[last_idx] == 'E');

            printf("[WASM] Tick %llu | Rate: %.2f MB/s | Integrity: %s\n", (unsigned long long)iteration,
                   (double)DIRTY_MB_PER_SEC, integrity_ok ? "OK" : "CORRUPTED!");
        }

        usleep(STEP_MS * 1000);
    }

    return 0;
}