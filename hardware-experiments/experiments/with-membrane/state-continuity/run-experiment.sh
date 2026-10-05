#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ANSIBLE_DIR="$SCRIPT_DIR/ansible"
INVENTORY="$ANSIBLE_DIR/hosts.ini"
SETUP_PLAYBOOK="$ANSIBLE_DIR/setup.yml"
TEARDOWN_PLAYBOOK="$ANSIBLE_DIR/teardown.yml"
RESULTS_DIR="$SCRIPT_DIR/results"

mkdir -p "$RESULTS_DIR"

echo "Running setup..."
ansible-playbook -i "$INVENTORY" "$SETUP_PLAYBOOK"

# Hosts
SAT1="192.168.10.11"
SAT2="192.168.10.12"
SAT1_NAME="sat1"
SAT2_NAME="sat2"

SOURCE_IP=$SAT1
TARGET_IP=$SAT2
TARGET_NAME=$SAT2_NAME
EXPERIMENT_DIR="/home/pi/iot-2026/experiments/with-membrane/state-continuity"

NUM_HANDOVERS=150

echo "Waiting for benchmark to settle..."
sleep 5

for ((i=1; i<=NUM_HANDOVERS; i++)); do
    echo "Handover $i: Migrating from $SOURCE_IP to $TARGET_IP"
    
    # Trigger migration on the target node
    ansible -i "$INVENTORY" "$TARGET_NAME" \
        -m ansible.builtin.shell \
        -a "cd '$EXPERIMENT_DIR' && exec stdbuf -oL ./iwasm-arm64 \
            --migrate=${SOURCE_IP}:8010 \
            --migration-server=8010 \
            benchmark.wasm >> iwasm.log 2>&1" \
        -B 600 -P 0
        
    sleep 5
    
    # Swap source and target for next iteration
    TEMP_IP=$SOURCE_IP
    SOURCE_IP=$TARGET_IP
    TARGET_IP=$TEMP_IP
    
    TEMP_NAME=$TARGET_NAME
    if [ "$TARGET_NAME" == "$SAT1_NAME" ]; then
        TARGET_NAME=$SAT2_NAME
    else
        TARGET_NAME=$SAT1_NAME
    fi
done

echo "Running teardown and collecting logs..."
ansible-playbook -i "$INVENTORY" "$TEARDOWN_PLAYBOOK"

echo "Experiment complete. Logs collected in $RESULTS_DIR"
