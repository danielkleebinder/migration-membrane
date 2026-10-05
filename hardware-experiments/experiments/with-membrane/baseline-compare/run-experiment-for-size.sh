#!/bin/bash

# Set default dirty rate to 64 MB/s, allow override via the first script argument
DIRTY_RATE=${1:-64}
ITERATIONS=${2:-3}
BASE_RUN_DIR="runs/size"

echo "==================================================="
echo "Starting ${ITERATIONS}-Iteration Memory Size Benchmark Suite"
echo "Fixed Dirty Rate: ${DIRTY_RATE} MB/s"
echo "Base Output Directory: ./${BASE_RUN_DIR}/"
echo "==================================================="

# Outer loop for full iterations of the experiment suite
for ITER in $(seq 1 "$ITERATIONS"); do
    # Define the iteration-specific run directory so iterations don't overwrite each other
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

    # Loop MEM_SIZE from 100 MB to 1000 MB in steps of 100 MB
    for MEM_SIZE in $(seq 50 50 1000); do
        echo ""
        echo "---------------------------------------------------"
        echo "Running Step: Memory Size = ${MEM_SIZE} MB (Rate: ${DIRTY_RATE} MB/s)"
        echo "---------------------------------------------------"

        # ---------------------------------------------------
        # 1. MEMBRANE RUN (iwasm-arm64)
        # ---------------------------------------------------
        echo "[Membrane] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64 mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=$(( (MEM_SIZE / 50) + 1 ))"

        echo "[Membrane] Archiving logs..."
        [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/membrane/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/membrane/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"

        # ---------------------------------------------------
        # 2. PRE-COPY RUN (iwasm-arm64-pre-copy)
        # ---------------------------------------------------
        echo "[Pre-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-pre-copy mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=$(( (MEM_SIZE / 25) + 1 ))"

        echo "[Pre-Copy] Archiving logs..."
        [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/pre-copy/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/pre-copy/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"

        # ---------------------------------------------------
        # 3. POST-COPY RUN (iwasm-arm64-post-copy)
        # ---------------------------------------------------
        echo "[Post-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-post-copy mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=$(( (MEM_SIZE / 10) + 1 ))"

        echo "[Post-Copy] Archiving logs..."
        [ -f "sat1_iwasm.log" ] && mv sat1_iwasm.log "${RUN_DIR}/post-copy/it${ITER}_sat1_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"
        [ -f "sat2_iwasm.log" ] && mv sat2_iwasm.log "${RUN_DIR}/post-copy/it${ITER}_sat2_mem${MEM_SIZE}_rate${DIRTY_RATE}.log"

        # ---------------------------------------------------
        # 4. STOP-COPY RUN (iwasm-arm64-stop-copy)
        # ---------------------------------------------------
        echo "[Stop-Copy] Executing Ansible playbook..."
        ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-stop-copy mem_size=${MEM_SIZE} dirty_rate=${DIRTY_RATE} sleep_time=8"

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