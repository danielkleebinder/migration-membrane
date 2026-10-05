#!/bin/bash

# Create all necessary nested run directories
mkdir -p runs/multi/membrane
mkdir -p runs/multi/pre-copy
mkdir -p runs/multi/post-copy
mkdir -p runs/multi/stop-copy

# Run the ansible playbook 20 times
for i in {1..20}
do
    echo "=========================================="
    echo "=== Running iteration $i of 20 ==="
    echo "=========================================="

    # CLEANUP: Remove local files from previous loops to prevent stale data archiving
    rm -f results.csv sat1_iwasm.log sat2_iwasm.log

    # -------------------------------------------------------------------
    # MEMBRANE (Currently Commented Out)
    # -------------------------------------------------------------------
     echo "Running Ansible playbook for iwasm-arm64 (Membrane)..."
     ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64"

     if [ -f "results.csv" ]; then
         mv results.csv "runs/multi/membrane/results_it${i}.csv"
         echo "Saved: runs/multi/membrane/results_it${i}.csv"
     else
         echo "Warning: results.csv not found for iteration $i (membrane)"
     fi
     if [ -f "sat1_iwasm.log" ]; then
         mv sat1_iwasm.log "runs/multi/membrane/results_it${i}_sat1.log"
     fi
     if [ -f "sat2_iwasm.log" ]; then
         mv sat2_iwasm.log "runs/multi/membrane/results_it${i}_sat2.log"
     fi

     rm -f results.csv sat1_iwasm.log sat2_iwasm.log

    # -------------------------------------------------------------------
    # POST-COPY
    # -------------------------------------------------------------------
    echo "Running Ansible playbook for iwasm-arm64-post-copy (Post-Copy)..."
    ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-post-copy"

    if [ -f "results.csv" ]; then
        mv results.csv "runs/multi/post-copy/results_it${i}.csv"
        echo "Saved: runs/multi/post-copy/results_it${i}.csv"
    else
        echo "Warning: results.csv not found for iteration $i (post-copy)"
    fi

    if [ -f "sat1_iwasm.log" ]; then
        mv sat1_iwasm.log "runs/multi/post-copy/results_it${i}_sat1.log"
        echo "Saved: runs/multi/post-copy/results_it${i}_sat1.log"
    else
        echo "Warning: iwasm.log for sat1 not found for iteration $i (post-copy)"
    fi

    if [ -f "sat2_iwasm.log" ]; then
        mv sat2_iwasm.log "runs/multi/post-copy/results_it${i}_sat2.log"
        echo "Saved: runs/multi/post-copy/results_it${i}_sat2.log"
    else
        echo "Warning: iwasm.log for sat2 not found for iteration $i (post-copy)"
    fi

    # CLEANUP before next execution
    rm -f results.csv sat1_iwasm.log sat2_iwasm.log

    # -------------------------------------------------------------------
    # PRE-COPY
    # -------------------------------------------------------------------
    echo "Running Ansible playbook for iwasm-arm64-pre-copy (Pre-Copy)..."
    ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-pre-copy"

    if [ -f "results.csv" ]; then
        mv results.csv "runs/multi/pre-copy/results_it${i}.csv"
        echo "Saved: runs/multi/pre-copy/results_it${i}.csv"
    else
        echo "Warning: results.csv not found for iteration $i (pre-copy)"
    fi

    if [ -f "sat1_iwasm.log" ]; then
        mv sat1_iwasm.log "runs/multi/pre-copy/results_it${i}_sat1.log"
        echo "Saved: runs/multi/pre-copy/results_it${i}_sat1.log"
    else
        echo "Warning: iwasm.log for sat1 not found for iteration $i (pre-copy)"
    fi

    if [ -f "sat2_iwasm.log" ]; then
        mv sat2_iwasm.log "runs/multi/pre-copy/results_it${i}_sat2.log"
        echo "Saved: runs/multi/pre-copy/results_it${i}_sat2.log"
    else
        echo "Warning: iwasm.log for sat2 not found for iteration $i (pre-copy)"
    fi

    # CLEANUP before next execution
    rm -f results.csv sat1_iwasm.log sat2_iwasm.log

    # -------------------------------------------------------------------
    # STOP-COPY
    # -------------------------------------------------------------------
    echo "Running Ansible playbook for iwasm-arm64-stop-copy (Stop-Copy)..."
    ansible-playbook -i hosts.ini run.yml -e "iwasm_exe=iwasm-arm64-stop-copy"

    if [ -f "results.csv" ]; then
        mv results.csv "runs/multi/stop-copy/results_it${i}.csv"
        echo "Saved: runs/multi/stop-copy/results_it${i}.csv"
    else
        echo "Warning: results.csv not found for iteration $i (stop-copy)"
    fi

    if [ -f "sat1_iwasm.log" ]; then
        mv sat1_iwasm.log "runs/multi/stop-copy/results_it${i}_sat1.log"
        echo "Saved: runs/multi/stop-copy/results_it${i}_sat1.log"
    else
        echo "Warning: iwasm.log for sat1 not found for iteration $i (stop-copy)"
    fi

    if [ -f "sat2_iwasm.log" ]; then
        mv sat2_iwasm.log "runs/multi/stop-copy/results_it${i}_sat2.log"
        echo "Saved: runs/multi/stop-copy/results_it${i}_sat2.log"
    else
        echo "Warning: iwasm.log for sat2 not found for iteration $i (stop-copy)"
    fi

    # CLEANUP before next loop
    rm -f results.csv sat1_iwasm.log sat2_iwasm.log

done

echo "=========================================="
echo "All 20 iterations completed successfully!"
echo "=========================================="