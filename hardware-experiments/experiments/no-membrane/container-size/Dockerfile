FROM busybox:1.38.0

WORKDIR /app

# Accept a build argument for size in Megabytes (defaults to 0)
ARG FILL_SIZE_MB=0

# Clean build-time file inflation
RUN if [ "$FILL_SIZE_MB" -gt 0 ]; then \
        dd if=/dev/zero of=/app/dummy_weight.bin bs=1M count=$FILL_SIZE_MB; \
    fi

# Interrupt-aware loop to allow instant docker stop executions
CMD ["sh", "-c", "trap 'exit 0' TERM; while true; do sleep 1 & wait \$!; done"]
