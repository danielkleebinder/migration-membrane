#!/bin/bash

# Set default syscall bytes to 256, allow override via the first script argument
SYSCALL_BYTES=${1:-256}
BASE_RUN_DIR="runs/syscall_rate"

echo "==================================================="
echo "Starting 5-Iteration Syscall Rate Benchmark Suite"
echo "Fixed Syscall Bytes: ${SYSCALL_BYTES} bytes"
echo "Base Output Directory: ./${BASE_RUN_DIR}/"
echo "==================================================="

# Outer loop for 5 full iterations of the experiment suite
for ITER in $(seq 3 3); do
    RUN_DIR="${BASE_RUN_DIR}/iteration_${ITER}"

    # Ensure the iteration-specific output directory exists
    mkdir -p "$RUN_DIR"

    echo ""
    echo "###################################################"
    echo "Starting Iteration ${ITER} / 3"
    echo "Target Directory: ./${RUN_DIR}/"
    echo "###################################################"

    for SYSCALLS_PER_SEC in $(seq 16000 1000 30000); do
        echo ""
        echo "---------------------------------------------------"
        echo "Running Step: Syscalls per sec = ${SYSCALLS_PER_SEC}"
        echo "---------------------------------------------------"

        # ---------------------------------------------------
        # 1. MEMBRANE RUN (iwasm-arm64)
        # ---------------------------------------------------
        echo "[Membrane] Executing Ansible playbook..."

        # Fixed Bash arithmetic syntax
        if [ "$SYSCALLS_PER_SEC" -lt 24000 ]; then
          sleep_time=$(( (SYSCALLS_PER_SEC / 700) + 3 ))
          ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64 syscalls=${SYSCALLS_PER_SEC} syscall_bytes=${SYSCALL_BYTES} sleep_time=$(( sleep_time < 35 ? sleep_time : 35 ))"

          # Move and rename logs into the current iteration directory
          echo "[Membrane] Archiving logs..."
          if [ -f "sat1_iwasm.log" ]; then
              mv sat1_iwasm.log "${RUN_DIR}/sat1_membrane_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
          fi
          if [ -f "sat2_iwasm.log" ]; then
              mv sat2_iwasm.log "${RUN_DIR}/sat2_membrane_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
          fi
        fi

        # ---------------------------------------------------
        # 2. PRE-COPY RUN (iwasm-arm64-pre-copy)
        # ---------------------------------------------------
        echo "[Pre-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-pre-copy syscalls=${SYSCALLS_PER_SEC} syscall_bytes=${SYSCALL_BYTES} sleep_time=6"

        # Move and rename logs into the current iteration directory
        echo "[Pre-Copy] Archiving logs..."

        # Fixed variable names from MEM_SIZE/DIRTY_RATE to SYSCALLS_PER_SEC/SYSCALL_BYTES
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_precopy_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_precopy_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
        fi

        # ---------------------------------------------------
        # 2. POST-COPY RUN (iwasm-arm64-post-copy)
        # ---------------------------------------------------
        echo "[Post-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-post-copy syscalls=${SYSCALLS_PER_SEC} syscall_bytes=${SYSCALL_BYTES} sleep_time=6"

        # Move and rename logs into the current iteration directory
        echo "[Post-Copy] Archiving logs..."

        # Fixed variable names from MEM_SIZE/DIRTY_RATE to SYSCALLS_PER_SEC/SYSCALL_BYTES
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_postcopy_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_postcopy_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
        fi

        # ---------------------------------------------------
        # 3. STOP-COPY RUN (iwasm-arm64-stop-copy)
        # ---------------------------------------------------
        echo "[Stop-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-stop-copy syscalls=${SYSCALLS_PER_SEC} syscall_bytes=${SYSCALL_BYTES} sleep_time=5"

        # Move and rename logs into the current iteration directory
        echo "[Stop-Copy] Archiving logs..."
        if [ -f "sat1_iwasm.log" ]; then
            mv sat1_iwasm.log "${RUN_DIR}/sat1_stopcopy_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
        fi
        if [ -f "sat2_iwasm.log" ]; then
            mv sat2_iwasm.log "${RUN_DIR}/sat2_stopcopy_syscalls${SYSCALLS_PER_SEC}_bytes${SYSCALL_BYTES}.log"
        fi

    done

    echo ""
    echo "Completed Iteration ${ITER} successfully."
done

echo ""
echo "==================================================="
echo "All 5 benchmark iterations completed successfully!"
echo "Logs are securely structured under ./${BASE_RUN_DIR}/iteration_{1..5}/"
echo "==================================================="