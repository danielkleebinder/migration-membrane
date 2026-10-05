#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RESULTS_DIR="${RESULTS_DIR:-$SCRIPT_DIR/results}"

command -v tshark >/dev/null || { echo "tshark is required to process tcpdump captures" >&2; exit 2; }
mkdir -p "$RESULTS_DIR"

# Try to determine EXPERIMENT_START_EPOCH from existing files if not provided
# We can look at sat1_host-metrics.csv: StartTimeMs = TimestampMs - TimeS * 1000
if [[ -z "${EXPERIMENT_START_EPOCH:-}" ]]; then
    if [[ -f "$RESULTS_DIR/sat1_host-metrics.csv" ]]; then
        # Use the first sample to estimate start epoch
        EXPERIMENT_START_EPOCH=$(awk -F, 'NR==2 { printf "%.6f", ($2 - $1*1000)/1000 }' "$RESULTS_DIR/sat1_host-metrics.csv")
        echo "Estimated EXPERIMENT_START_EPOCH from sat1_host-metrics.csv: $EXPERIMENT_START_EPOCH"
    else
        echo "EXPERIMENT_START_EPOCH not set and sat1_host-metrics.csv missing. Using 0."
        EXPERIMENT_START_EPOCH=0
    fi
fi

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
    echo "Processing $file..."
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
}

echo "Combining samples..."
combine_samples || true
echo "Processing PCAPs..."
process_pcaps || true

if [[ -f analyze_recurrent_results.py ]]; then
  echo "Running analyze_recurrent_results.py..."
  python3 analyze_recurrent_results.py "$RESULTS_DIR/results.csv" \
    --host-samples "$RESULTS_DIR/host-samples.csv" \
    --sat1-log "$RESULTS_DIR/sat1_iwasm.log" \
    --sat2-log "$RESULTS_DIR/sat2_iwasm.log" \
    --migration-traffic "$RESULTS_DIR/migration-traffic.csv"
fi

if [[ -f stats.py ]]; then
  echo "Running stats.py..."
  python3 stats.py
fi

echo "Analysis complete. Results: $RESULTS_DIR"