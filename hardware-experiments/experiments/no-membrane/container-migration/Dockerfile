# ==========================================
# STAGE 1: Compile lookbusy from source
# ==========================================
FROM debian:bookworm-slim AS builder

# Install necessary compilation utilities
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    autoconf \
    automake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN git clone https://github.com/flow2000/lookbusy.git .

# Build the binary
RUN chmod a+x configure
RUN ./configure && make && make install

# ==========================================
# STAGE 2: Lightweight runtime footprint
# ==========================================
FROM debian:bookworm-slim

# Copy the standalone compiled executable from the builder stage
COPY --from=builder /src/lookbusy /usr/local/bin/lookbusy

# By default, lookbusy runs in the foreground, keeping the container active.
# ENTRYPOINT appends any runtime parameters straight to the executable execution.
ENTRYPOINT ["/usr/local/bin/lookbusy"]

# Provide a safe default configuration (e.g., 10% CPU usage) if no arguments are passed
CMD ["-c", "10"]
