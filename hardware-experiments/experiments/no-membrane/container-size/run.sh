#!/bin/bash

IMAGE_NAME="cmapss-sweep-app"
CONTAINER_NAME="test-container"
SAT2_IP="192.168.10.12"
SAT2_USER="root"
RAMDISK_DIR="/mnt/ramdisk"
CSV_OUT="migration_sweep_results.csv"

# Initialize a clean CSV output file with headers
echo "added_mb,stop_ms,export_ms,transfer_ms,reinstantiate_ms,total_ms" > "$CSV_OUT"

echo "========================================================="
echo " Starting Automated Multi-Size Migration Latency Sweep"
echo " Target Destination: sat2 (${SAT2_IP})"
echo " Output Log: ${CSV_OUT}"
echo "========================================================="

# Sweep from 0 MB to 500 MB in steps of 50 MB
for SIZE_MB in $(seq 0 50 500); do
    echo "---------------------------------------------------------"
    echo "[SWEEP STEP] Evaluating variant: +${SIZE_MB} MB"
    echo "---------------------------------------------------------"

    # 1. Environment Scrubber (Local)
    docker rm -f $CONTAINER_NAME 2>/dev/null
    docker rmi "$IMAGE_NAME:sz-${SIZE_MB}MB" 2>/dev/null

    # 2. Build the targeted inflated image variant using our BusyBox Dockerfile
    echo "[Build] Compiling container with FILL_SIZE_MB=${SIZE_MB}..."
    docker build --build-arg FILL_SIZE_MB="$SIZE_MB" -t "$IMAGE_NAME:sz-${SIZE_MB}MB" . > /dev/null
    
    # 3. Spin up the local source instance
    docker run -d --name $CONTAINER_NAME "$IMAGE_NAME:sz-${SIZE_MB}MB" > /dev/null

    # Brief cooldown to let cgroups settle down before taking measurements
    sleep 2

    # --- CRITICAL BLACKOUT WINDOW BEGINS ---
    start_time_total=$(date +%s%N)

    # Phase 1: Gracefully Stop Container
    start_stop=$(date +%s%N)
    sudo docker stop -t 2 "$CONTAINER_NAME" > /dev/null
    end_stop=$(date +%s%N)
    stopping_duration_ms=$(( (end_stop - start_stop) / 1000000 ))

    # Phase 2: Export Container Filesystem Layer to RAM Disk
    start_export=$(date +%s%N)
    sudo docker export "$CONTAINER_NAME" > "${RAMDISK_DIR}/container_rootfs.tar"
    end_export=$(date +%s%N)
    exporting_duration_ms=$(( (end_export - start_export) / 1000000 ))

    # Phase 3: Transfer Tarball over the space-emulated link to Target RAM Disk
    start_transfer=$(date +%s%N)
    sudo rsync -aqz -e "ssh -i /home/pi/.ssh/id_ed25519" "${RAMDISK_DIR}/container_rootfs.tar" "${SAT2_USER}@${SAT2_IP}:${RAMDISK_DIR}/"
    end_transfer=$(date +%s%N)
    transfer_duration_ms=$(( (end_transfer - start_transfer) / 1000000 ))

    # Phase 4: Import, Re-instantiate, and Execute on sat2 RAM Disk
    start_reinstantiate=$(date +%s%N)
    ssh -i /home/pi/.ssh/id_ed25519 ${SAT2_USER}@${SAT2_IP} "
        sudo cat ${RAMDISK_DIR}/container_rootfs.tar | sudo docker import - cold_migrated_app:latest > /dev/null && \
        sudo docker rm -f ${CONTAINER_NAME} 2>/dev/null && \
        sudo docker run -d --name ${CONTAINER_NAME} -p 5005:5005/tcp cold_migrated_app:latest > /dev/null && \
        rm -f ${RAMDISK_DIR}/container_rootfs.tar
    " > /dev/null

    # Local storage cleanup
    rm -f "${RAMDISK_DIR}/container_rootfs.tar"
    end_reinstantiate=$(date +%s%N)
    reinstantiating_duration_ms=$(( (end_reinstantiate - start_reinstantiate) / 1000000 ))

    end_time_total=$(date +%s%N)
    # --- CRITICAL BLACKOUT WINDOW ENDS ---

    total_duration_ms=$(( (end_time_total - start_time_total) / 1000000 ))

    # Append data row straight into the target evaluation CSV file
    echo "${SIZE_MB},${stopping_duration_ms},${exporting_duration_ms},${transfer_duration_ms},${reinstantiating_duration_ms},${total_duration_ms}" >> "$CSV_OUT"

    echo "[RESULT] +${SIZE_MB}MB -> Stop: ${stopping_duration_ms}ms | Export: ${exporting_duration_ms}ms | Xfer: ${transfer_duration_ms}ms | Wake: ${reinstantiating_duration_ms}ms | Total: ${total_duration_ms}ms"

    # Post-step cleanup: Remove old images to prevent dangling layer leaks in storage
    docker rm -f $CONTAINER_NAME 2>/dev/null
    docker rmi "$IMAGE_NAME:sz-${SIZE_MB}MB" 2>/dev/null
    docker image prune -f > /dev/null
done

echo "========================================================="
echo " [SUCCESS] Sweep completed smoothly."
echo " File successfully written to: $(pwd)/${CSV_OUT}"
echo "========================================================="
