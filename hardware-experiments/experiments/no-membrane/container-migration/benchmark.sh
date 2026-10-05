#!/bin/bash

# Configuration
SAT1="root@sat1"
SAT2="root@sat2"
RAMDISK="/mnt/ramdisk/container-migration/checkpoints"
CSV_FILE="results_container_migration.csv"

# Initialize CSV Headers
echo "profile,load,iteration,checkpoint,sync,create,start,total" > $CSV_FILE

# Function to perform mandatory cleanup
cleanup_node() {
    local node=$1
    echo "Cleaning up $node..."
    ssh $node "docker rm -f loadgen >/dev/null 2>&1; \
               rm -rf $RAMDISK/cp_handover; \
               rm -rf /tmp/ctrd-checkpoint* /tmp/containerd-shim*" >/dev/null 2>&1
}

# Function to run a single migration cycle and log it
run_migration() {
    local type=$1
    local load=$2
    local iteration=$3
    local run_args=$4

    echo "Running profile: $type @ $load (Iteration $iteration)..."

    # 1. Clean environment and start lookbusy on sat1
    ssh $SAT2 "docker rm -f loadgen" >/dev/null 2>&1
    ssh $SAT1 "docker rm -f loadgen && rm -rf $RAMDISK/cp_handover" >/dev/null 2>&1
    ssh $SAT1 "docker run --rm --name loadgen --network=host --privileged -d $run_args" >/dev/null 2>&1
    sleep 5 # Allow lookbusy to reach target utilization

    # 2. Measure Checkpoint Creation (sat1)
    echo "Creating checkpoint: $type @ $load..."
    t0=$(date +%s%3N)
    ssh $SAT1 "docker checkpoint create --checkpoint-dir=$RAMDISK loadgen cp_handover"
    t1=$(date +%s%3N)

    # 3. Measure Rsync Transfer (sat1 -> sat2)
    echo "Synchronize checkpoint from sat1 to sat2: $type @ $load..."
    ssh $SAT2 "rm -rf $RAMDISK/cp_handover" >/dev/null 2>&1
    t2=$(date +%s%3N)
    ssh $SAT1 "rsync -avz --delete $RAMDISK/ root@sat2:$RAMDISK/"
    t3=$(date +%s%3N)

    # 4. Measure Container Creation (sat2)
    echo "Create container: $type @ $load..."
    t4=$(date +%s%3N)
    ssh $SAT2 "docker create --name loadgen --network=host --privileged $run_args" >/dev/null
    t5=$(date +%s%3N)

    # 5. Measure Native Restoration (sat2)
    echo "Restore container: $type @ $load..."
    ssh $SAT2 "CID=\$(docker inspect --format='{{.Id}}' loadgen) && \
               rm -rf /var/lib/docker/containers/\$CID/checkpoints && \
               cp -r $RAMDISK /var/lib/docker/containers/\$CID/checkpoints && \
               rm -rf $RAMDISK/cp_handover" >/dev/null 2>&1
    t6=$(date +%s%3N)
    ssh $SAT2 "docker start --checkpoint cp_handover loadgen" >/dev/null
    t7=$(date +%s%3N)

    # Calculate metrics
    chkpt_time=$((t1 - t0))
    rsync_time=$((t3 - t2))
    create_time=$((t5 - t4))
    start_time=$((t7 - t6))
    total_time=$((chkpt_time + rsync_time + create_time + start_time))

    # Append to CSV
    echo "$type,$load,$iteration,$chkpt_time,$rsync_time,$create_time,$start_time,$total_time" >> $CSV_FILE
    echo "  -> Completed in ${total_time}ms"

    # Cleanup immediately after run
    cleanup_node $SAT1
    cleanup_node $SAT2
}

# ==========================================
# EXPERIMENT LOOPS
# ==========================================

# 1. CPU Stress (0% to 80% in 10% steps)
for i in {1..5}; do
    for cpu in {0..100..10}; do
        run_migration "CPU" "${cpu}%" "$i" "-it lookbusy-loadgen -c $cpu"
    done
done

# 2. Memory Stress (0MB to 4000MB in 500MB steps)
for i in {1..5}; do
    for mem in {0..500..50}; do
        run_migration "Memory" "${mem}MB" "$i" "-it lookbusy-loadgen -m ${mem}MB"
    done
done

# 3. Disk Stress (0GB to 10GB in 1GB steps)
for i in {1..5}; do
    for disk in {0..1000..100}; do
        # Note: lookbusy requires a file path to generate disk load.
        # We write it to /tmp so it stays inside the container's writable overlayfs layer,
        # forcing CRIU to package it into the checkpoint dump.
        run_migration "Disk" "${disk}MB" "$i" "-it lookbusy-loadgen -d ${disk}MB -f /tmp/load.tmp"
    done
done

echo "Benchmark complete! Results saved to $CSV_FILE."