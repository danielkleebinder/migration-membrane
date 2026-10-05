#!/bin/bash

NODES=("sat1" "sat2" "sensor")
RAM_PATH="/mnt/ramdisk"
: '
# 1. System update
for node in "${NODES[@]}"; do
    echo -e "-> Update system on $node (apt update & full-upgrade)..."
    ssh -t "$node" "sudo apt-get update && sudo apt-get full-upgrade -y"
done

# 2. Restart Raspberry Pis
for node in "${NODES[@]}"; do
    echo -e "-> Restarting $node..."
    ssh -t "$node" "sudo reboot"
done

# 3. Wait, until the Raspberry Pis are ready
echo -e "$-> Waiting 40 seconds for nodes to boot back up..."
sleep 40

# 4. Install OCI runtime and CRIU
for node in "${NODES[@]}"; do
    echo -e "-> Installing OCI runtimes and CRIU on $node..."
    ssh -t "$node" "sudo apt-get update && sudo apt-get install -y runc crun criu"
done

# 5. Install Wasmtime
for node in "${NODES[@]}"; do
    echo -e "-> Install Wasmtime on $node..."
    ssh "$node" "curl https://wasmtime.dev/install.sh -sSf | bash"

    echo -e "-> Verify installation on $node"
    ssh "$node" "~/.wasmtime/bin/wasmtime --version"

    echo -e "-> Wasmtime is now ready on $node"
done
'
# 6. Setup RAM disk to avoid slower hard drive I/O
for node in "${NODES[@]}"; do
    echo -e "-> Setup ram disk on $node..."
    ssh -t "$node" "sudo mkdir -p $RAM_PATH && sudo mount -t tmpfs -o size=512M tmpfs $RAM_PATH && sudo chown -R pi:pi $RAM_PATH && df -h | grep ramdisk"
done
