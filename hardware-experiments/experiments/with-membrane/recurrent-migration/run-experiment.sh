#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 N INTERVAL_SECONDS" >&2
  exit 2
fi

MIGRATIONS="$1"
INTERVAL="$2"
[[ "$MIGRATIONS" =~ ^[1-9][0-9]*$ ]] || { echo "N must be a positive integer" >&2; exit 2; }
[[ "$INTERVAL" =~ ^[0-9]+([.][0-9]+)?$ ]] || { echo "INTERVAL_SECONDS must be non-negative" >&2; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ANSIBLE_DIR="${ANSIBLE_DIR:-$SCRIPT_DIR/ansible}"
INVENTORY="${INVENTORY:-$ANSIBLE_DIR/hosts.ini}"
SETUP_PLAYBOOK="${SETUP_PLAYBOOK:-$ANSIBLE_DIR/setup.yml}"
TEARDOWN_PLAYBOOK="${TEARDOWN_PLAYBOOK:-$ANSIBLE_DIR/teardown.yml}"

SAT1="${SAT1:-192.168.10.11}"
SAT2="${SAT2:-192.168.10.12}"
SSH_USER="${SSH_USER:-root}"
START_DELAY="${START_DELAY:-60}"
WARMUP_SECONDS="${WARMUP_SECONDS:-5}"
REMOTE_DIR="/home/pi/iot-2026/experiments/with-membrane/recurrent-migration"
RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"

for file in "$INVENTORY" "$SETUP_PLAYBOOK" "$TEARDOWN_PLAYBOOK"; do
  [[ -f "$file" ]] || { echo "Missing file: $file" >&2; exit 2; }
done
command -v tshark >/dev/null || { echo "tshark is required to process tcpdump captures" >&2; exit 2; }
mkdir -p "$RESULTS_DIR"

epoch_now() { date +%s.%N; }
relative_time() {
  awk -v now="$(epoch_now)" -v start="$EXPERIMENT_START_EPOCH" \
    'BEGIN { printf "%.6f", now - start }'
}

trigger_migration() {
  local source="$1" target="$2"
  ssh -f -n -o BatchMode=yes "$SSH_USER@$target" \
    "pkill -9 -f '[i]wasm-arm64.*benchmark[.]wasm' 2>/dev/null || true
     cd '$REMOTE_DIR' && exec ./start-runtime.sh '$source'"
}

verify_remote_metrics() {
  local host="$1"
  ssh -o BatchMode=yes "$SSH_USER@$host" \
    "pid=\$(< '$REMOTE_DIR/metrics.pid')
     kill -0 \"\$pid\" 2>/dev/null
     awk 'END { exit !(NR > 1) }' '$REMOTE_DIR/host-metrics.csv'"
}

combine_samples() {
  local file
  for file in "$RESULTS_DIR/sat1_host-metrics.csv" "$RESULTS_DIR/sat2_host-metrics.csv"; do
    if [[ ! -f "$file" ]] || ! awk 'END { exit !(NR > 1) }' "$file"; then
      echo "Missing CPU/memory samples in $file" >&2
      return 1
    fi
  done

  head -n 1 "$RESULTS_DIR/sat1_host-metrics.csv" \
    > "$RESULTS_DIR/host-samples.csv"
  tail -n +2 "$RESULTS_DIR/sat1_host-metrics.csv" \
    >> "$RESULTS_DIR/host-samples.csv"
  tail -n +2 "$RESULTS_DIR/sat2_host-metrics.csv" \
    >> "$RESULTS_DIR/host-samples.csv"
}

process_pcaps() {
  local file
  printf 'TimeS,TimestampMs,Bytes,Channel\n' > "$RESULTS_DIR/network-packets.csv"
  for file in "$RESULTS_DIR/sat1_network.pcap" "$RESULTS_DIR/sat2_network.pcap"; do
    [[ -s "$file" ]] || continue
    tshark -r "$file" \
      -Y 'tcp.port == 8010 || udp.port == 8010 || tcp.port == 8011 || udp.port == 8011' \
      -T fields \
      -e frame.time_epoch -e frame.len \
      -e tcp.srcport -e tcp.dstport -e udp.srcport -e udp.dstport \
      -E separator=, -E quote=n -E occurrence=f 2>/dev/null |
    awk -F, -v start="$EXPERIMENT_START_EPOCH" '
      {
        channel = ""
        for (field = 3; field <= 6; field++) {
          if ($field == 8010) channel = "base"
          if ($field == 8011) channel = "event"
        }
        if (channel != "" && $1 >= start) {
          split($1, parts, ".")
          # parts[2] is the fractional part of seconds from frame.time_epoch
          # It can have varying number of digits. We want a fixed format for TimestampMs.
          # We use 6 digits for microseconds as common in these logs.
          # Frame time epoch is seconds.microseconds (or nanoseconds).
          # parts[1] is seconds. parts[2] is the rest.
          # TimestampMs should be (seconds * 1000) + (microseconds / 1000).
          # In the desired format: 1787219542667.314000
          # parts[1] is 1787219542.
          # parts[2] is 667314000 (if nanoseconds).
          # parts[1]parts[2][1-3].parts[2][4-6]
          frac = parts[2]
          while (length(frac) < 9) frac = frac "0"
          printf "%.6f,%s%s.%s,%s,%s\n", $1 - start, parts[1], substr(frac, 1, 3), substr(frac, 4), $2, channel
        }
      }
    ' >> "$RESULTS_DIR/network-packets.csv"
  done

  {
    head -n 1 "$RESULTS_DIR/network-packets.csv"
    tail -n +2 "$RESULTS_DIR/network-packets.csv" | sort -t, -k1,1n
  } > "$RESULTS_DIR/network-packets.sorted.csv"
  mv "$RESULTS_DIR/network-packets.sorted.csv" "$RESULTS_DIR/network-packets.csv"

  printf 'TimeS,MigrationBytes\n' > "$RESULTS_DIR/migration-traffic.csv"
  awk -F, 'NR > 1 { print $1 "," $3 }' "$RESULTS_DIR/network-packets.csv" \
    >> "$RESULTS_DIR/migration-traffic.csv"

  awk -F, '
    BEGIN { migration = 1; OFS = "," }
    NR == FNR {
      if (FNR > 1) {
        migrations++
        start[migrations] = $2
        end[migrations] = $3
      }
      next
    }
    FNR > 1 {
      while (migration <= migrations && $1 > end[migration]) migration++
      if (migration <= migrations && $1 >= start[migration]) {
        if ($4 == "base") base[migration] += $3
        if ($4 == "event") event[migration] += $3
      }
    }
    END {
      print "Migration,BaseBytes,EventBytes"
      for (migration = 1; migration <= migrations; migration++)
        print migration, base[migration] + 0, event[migration] + 0
    }
  ' "$RESULTS_DIR/migrations.csv" "$RESULTS_DIR/network-packets.csv" \
    > "$RESULTS_DIR/migration-bytes.csv"

  awk -F, '
    BEGIN { OFS = "," }
    NR == FNR {
      if (FNR > 1) {
        base[$1] = $2
        event[$1] = $3
      }
      next
    }
    FNR == 1 { print; next }
    {
      $6 = base[$1] + 0
      $7 = event[$1] + 0
      $8 = $6 + $7
      print
    }
  ' "$RESULTS_DIR/migration-bytes.csv" "$RESULTS_DIR/migrations.csv" \
    > "$RESULTS_DIR/migrations.with-bytes.csv"
  mv "$RESULTS_DIR/migrations.with-bytes.csv" "$RESULTS_DIR/migrations.csv"
  unlink "$RESULTS_DIR/migration-bytes.csv"
}

setup_complete=0
cleanup() {
  local status=$?
  trap - EXIT
  if (( setup_complete )); then
    ansible-playbook -i "$INVENTORY" "$TEARDOWN_PLAYBOOK" \
      -e "results_dir=$RESULTS_DIR" || true
    combine_samples || true
  fi
  exit "$status"
}
trap cleanup EXIT

EXPERIMENT_START_EPOCH="$(awk -v now="$(epoch_now)" -v delay="$START_DELAY" \
  'BEGIN { printf "%.6f", now + delay }')"

echo "Preparing experiment; synchronized start is $EXPERIMENT_START_EPOCH"
ansible-playbook -i "$INVENTORY" "$SETUP_PLAYBOOK" \
  -e "experiment_start_epoch=$EXPERIMENT_START_EPOCH"
setup_complete=1

if awk -v now="$(epoch_now)" -v start="$EXPERIMENT_START_EPOCH" \
    'BEGIN { exit !(now >= start) }'; then
  echo "Setup exceeded START_DELAY=${START_DELAY}s; increase START_DELAY and retry" >&2
  exit 1
fi

while awk -v now="$(epoch_now)" -v start="$EXPERIMENT_START_EPOCH" \
    'BEGIN { exit !(now < start) }'; do
  sleep 0.1
done
sleep "$WARMUP_SECONDS"

for host in "$SAT1" "$SAT2"; do
  if ! verify_remote_metrics "$host"; then
    echo "Metrics collector on $host is not running or has produced no samples" >&2
    ssh -o BatchMode=yes "$SSH_USER@$host" \
      "tail -n 20 '$REMOTE_DIR/metrics.log'" >&2 || true
    exit 1
  fi
done

printf 'Migration,StartTimeS,EndTimeS,Completed,DowntimeMs,BaseBytes,EventBytes,TotalBytes,ReplayLag\n' \
  > "$RESULTS_DIR/migrations.csv"

SOURCE="$SAT1"
TARGET="$SAT2"
for ((INDEX = 1; INDEX <= MIGRATIONS; INDEX++)); do
  started="$(relative_time)"

  echo "Migration $INDEX/$MIGRATIONS: $SOURCE -> $TARGET"
  trigger_migration "$SOURCE" "$TARGET"
  sleep "$INTERVAL"

  ended="$(relative_time)"
  printf '%s,%s,%s,1,,,,,\n' \
    "$INDEX" "$started" "$ended" >> "$RESULTS_DIR/migrations.csv"

  temporary="$SOURCE"
  SOURCE="$TARGET"
  TARGET="$temporary"
done

ansible-playbook -i "$INVENTORY" "$TEARDOWN_PLAYBOOK" \
  -e "results_dir=$RESULTS_DIR"
setup_complete=0
combine_samples
process_pcaps

if [[ -f analyze_recurrent_results.py ]]; then
  python3 analyze_recurrent_results.py "$RESULTS_DIR/results.csv" \
    --host-samples "$RESULTS_DIR/host-samples.csv" \
    --migrations "$RESULTS_DIR/migrations.csv" \
    --migration-traffic "$RESULTS_DIR/migration-traffic.csv"
fi

echo "Experiment complete. Results: $RESULTS_DIR"