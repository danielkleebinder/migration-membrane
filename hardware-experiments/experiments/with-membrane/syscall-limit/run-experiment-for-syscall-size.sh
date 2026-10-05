#!/bin/bash

# Set default syscall rate to 5000 calls/sec, allow override via the first script argument
SYSCALL_RATE=${1:-10000}
BASE_RUN_DIR="runs/syscall_payload"

echo "==================================================="
echo "Starting 5-Iteration Syscall Payload Size Suite"
echo "Fixed Syscall Rate: ${SYSCALL_RATE} calls/sec"
echo "Base Output Directory: ./${BASE_RUN_DIR}/"
echo "==================================================="

# Outer loop for 5 full iterations of the experiment suite
for ITER in $(seq 1 3); do
    RUN_DIR="${BASE_RUN_DIR}/iteration_${ITER}"

    # Ensure the iteration-specific output directory exists
    mkdir -p "$RUN_DIR"

    echo ""
    echo "###################################################"
    echo "Starting Iteration ${ITER} / 3"
    echo "Target Directory: ./${RUN_DIR}/"
    echo "###################################################"

    # Sweep payload sizes: e.g., from 64 bytes up to 1024 bytes in steps of 64 or 128
    for SYSCALL_BYTES in $(seq 1024 1024 16384); do
        echo ""
        echo "---------------------------------------------------"
        echo "Running Step: Syscall Payload Size = ${SYSCALL_BYTES} bytes"
        echo "---------------------------------------------------"

        # ---------------------------------------------------
        # 1. MEMBRANE RUN (iwasm-arm64)
        # ---------------------------------------------------
        echo "[Membrane] Executing Ansible playbook..."

        # Adjust sleep time dynamically based on payload size if needed, or keep it standard
        sleep_time=10
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64 syscalls=${SYSCALL_RATE} syscall_bytes=${SYSCALL_BYTES} sleep_time=${sleep_time}"

        # Move and rename logs into the current iteration directory
        echo "[Membrane] Archiving logs..."
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_membrane_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_membrane_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi

        # ---------------------------------------------------
        # 2. PRE-COPY RUN (iwasm-arm64-pre-copy)
        # ---------------------------------------------------
        echo "[Pre-Copy] Executing Ansible playbook..."
        sleep_time=6
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-pre-copy syscalls=${SYSCALL_RATE} syscall_bytes=${SYSCALL_BYTES} sleep_time=${sleep_time}"

        # Move and rename logs into the current iteration directory
        echo "[Pre-Copy] Archiving logs..."
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_precopy_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_precopy_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi

        # ---------------------------------------------------
        # 2. POST-COPY RUN (iwasm-arm64-post-copy)
        # ---------------------------------------------------
        echo "[Post-Copy] Executing Ansible playbook..."
        sleep_time=6
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-post-copy syscalls=${SYSCALL_RATE} syscall_bytes=${SYSCALL_BYTES} sleep_time=${sleep_time}"

        # Move and rename logs into the current iteration directory
        echo "[Post-Copy] Archiving logs..."
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_postcopy_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_postcopy_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi

        # ---------------------------------------------------
        # 3. STOP-COPY RUN (iwasm-arm64-stop-copy)
        # ---------------------------------------------------
        echo "[Stop-Copy] Executing Ansible playbook..."
        sleep_time=5
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-stop-copy syscalls=${SYSCALL_RATE} syscall_bytes=${SYSCALL_BYTES} sleep_time=${sleep_time}"

        # Move and rename logs into the current iteration directory
        echo "[Stop-Copy] Archiving logs..."
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_stopcopy_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_stopcopy_syscalls${SYSCALL_RATE}_bytes${SYSCALL_BYTES}.log"
        fi

    done

    echo ""
    echo "Completed Iteration ${ITER} successfully."
done

echo ""
echo "==================================================="
echo "All 5 benchmark iterations completed successfully!"
echo "Logs are securely structured under ./${BASE_RUN_DIR}/iteration_{1..3}/"
echo "==================================================="