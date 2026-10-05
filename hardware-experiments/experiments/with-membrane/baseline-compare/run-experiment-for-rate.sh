#!/bin/bash

# Set default parameters, allow overrides via script arguments
MEM_SIZE=${1:-256}
ITERATIONS=${2:-3}
BASE_RUN_DIR="runs/rate"

echo "==================================================="
echo "Starting ${ITERATIONS}-Iteration Migration Benchmark Suite"
echo "Memory Size: ${MEM_SIZE} MB"
echo "Base Output Directory: ./${BASE_RUN_DIR}/"
echo "==================================================="

# Outer loop for full iterations of the experiment suite
for ITER in $(seq 1 "$ITERATIONS"); do
    # Define the iteration-specific run directory
    RUN_DIR="${BASE_RUN_DIR}"

    # Create directories for each migration strategy inside this iteration
    mkdir -p "${RUN_DIR}/membrane"
    mkdir -p "${RUN_DIR}/pre-copy"
    mkdir -p "${RUN_DIR}/post-copy"
    mkdir -p "${RUN_DIR}/stop-copy"

    echo ""
    echo "###################################################"
    echo "Starting Iteration ${ITER} / ${ITERATIONS}"
    echo "Target Directory: ./${RUN_DIR}/"
    echo "###################################################"

    for DIRTY_RATE in $(seq 10 10 140); do
        echo ""
        echo "---------------------------------------------------"
        echo "Running Step: Dirty Rate = ${DIRTY_RATE} MB/s"
        echo "---------------------------------------------------"

        # ---------------------------------------------------
        # 1. MEMBRANE RUN
        # ---------------------------------------------------
        echo "[Membrane] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64 mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=4"

        echo "[Membrane] Archiving logs..."
        [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/membrane/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/membrane/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"

        # ---------------------------------------------------
        # 2. PRE-COPY RUN
        # ---------------------------------------------------
        if [ "$DIRTY_RATE" -lt 120 ]; then
            echo "[Pre-Copy] Executing Ansible playbook..."
            ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-pre-copy mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=${DIRTY_RATE}"

            echo "[Pre-Copy] Archiving logs..."
            [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/pre-copy/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
            [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/pre-copy/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        else
            echo "[Pre-Copy] Skipping dirty_rate=${DIRTY_RATE} MB/s (exceeds convergence threshold)"
        fi

        # ---------------------------------------------------
        # 3. POST-COPY RUN
        # ---------------------------------------------------
        echo "[Post-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-post-copy mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=${DIRTY_RATE}"

        echo "[Post-Copy] Archiving logs..."
        [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/post-copy/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/post-copy/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"

        # ---------------------------------------------------
        # 4. STOP-COPY RUN
        # ---------------------------------------------------
        echo "[Stop-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-stop-copy mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=3"

        echo "[Stop-Copy] Archiving logs..."
        [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/stop-copy/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/stop-copy/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"

    done

    echo ""
    echo "Completed Iteration ${ITER} successfully."
done

echo ""
echo "==================================================="
echo "All benchmark iterations completed successfully!"
echo "Logs are securely structured under ./${BASE_RUN_DIR}/iteration_*/"
echo "==================================================="