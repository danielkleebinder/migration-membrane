#include <stdio.h>
#include <unistd.h>

#define SLEEP_DURATION_MILLISECONDS 10

int
main()
{
    int counter = 0;
    printf("[DEBUG] Counter offset: %u (Hex: %p)\n", (unsigned int)&counter, (void *)&counter);

    ssize_t x = 0;
    while (1) {
        if (x % 100000 == 0) {
            printf("[WASM] Iteration %d...\n", counter++);
            fflush(stdout);
        }
        x++;
    }
}
