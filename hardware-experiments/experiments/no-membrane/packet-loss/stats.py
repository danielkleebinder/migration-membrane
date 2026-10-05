import numpy as np
import pandas as pd

RECEIVER_FILE = "results_packet_loss.csv"
DATASET_FILE = "../../datasets/50mbps_su_dcf_full.csv"
OUTPUT_FILE = "results_packet_loss_aggregated.csv"
FILTER_INTERVAL = 0.25 # Interval to keep in the output file (e.g., every 100ms)

try:
    # 1. Load the Receiver Data
    print(f"Loading receiver data from '{RECEIVER_FILE}'...")
    df_receiver = pd.read_csv(RECEIVER_FILE)
    df_receiver.columns = df_receiver.columns.str.strip()

    # Find the exact moment the experiment ended based on the last recorded packet
    max_receiver_time = df_receiver["Time"].max()
    print(f"-> Receiver log ends at: {max_receiver_time:.6f} seconds")

    # 2. Sort and save the received packets per the baseline requirement
    df_rec_sorted = df_receiver.sort_values(by="Sequence").reset_index(drop=True)

    # 3. Load the Ground-Truth Dataset (Handles quote fields automatically)
    print(f"Loading ground-truth dataset from '{DATASET_FILE}'...")
    df_dataset = pd.read_csv(DATASET_FILE)

    # Strip quotes and whitespace from dataset headers cleanly
    df_dataset.columns = df_dataset.columns.str.replace('"', '').str.strip()

    # Ensure critical columns are parsed as numeric structures
    df_dataset["Time"] = pd.to_numeric(df_dataset["Time"])
    df_dataset["No."] = pd.to_numeric(df_dataset["No."]).astype(int)

    # 4. Filter dataset to match what the sender actually transmitted
    df_transmitted = df_dataset[df_dataset["Time"] <= max_receiver_time].copy()

    # Map the 1-based 'No.' column to your 0-based 'Sequence' column
    df_transmitted["Sequence"] = df_transmitted["No."] - 1

    # 5. Explicitly rename columns before merging to guarantee key safety
    df_tx_sub = df_transmitted[["Sequence", "Time"]].rename(columns={"Time": "Time_true"})

    # Safely pull columns from receiver whether it contains a duplicate 'Time' column or not
    if "Time" in df_receiver.columns:
        df_rx_sub = df_receiver[["Sequence", "Latency", "Time"]].rename(columns={"Time": "Time_rec"})
    else:
        df_rx_sub = df_receiver[["Sequence", "Latency"]]

    # 6. Merge the datasets to expose the silent gaps
    df_analysis = pd.merge(
        df_tx_sub,
        df_rx_sub,
        on="Sequence",
        how="left"
    )

    # If Latency is NaN, the packet never reached the receiver
    df_analysis["Lost"] = df_analysis["Latency"].isna().astype(int)

    # 7. Group by the TRUE transmission time steps
    df_analysis["step"] = (np.floor(df_analysis["Time_true"] / FILTER_INTERVAL) * FILTER_INTERVAL).round(3)

    # 8. Aggregate Interval-by-Interval Metrics
    step_summary = (
        df_analysis.groupby("step")
        .agg(
            lost=("Lost", "sum"),
            received=("Lost", lambda x: len(x) - x.sum()),  # Total expected minus dropped
            latency=("Latency", "mean")  # Sum of latencies in the interval
        )
        .reset_index()
    )

    # 9. Print Evaluation Output and Save to CSV
    print(f"\n=== Global Evaluation Metrics ===")
    print(f"Total Expected Packets : {len(df_analysis)}")
    print(f"Total Packets Received  : {len(df_receiver)}")
    print(f"Total Packets Dropped   : {df_analysis['Lost'].sum()}")
    print(f"Overall Total Latency    : {df_receiver['Latency'].sum():.6f} ms")

    print(f"\nSaving aggregated results (interval={FILTER_INTERVAL}s) to '{OUTPUT_FILE}'...")
    step_summary.to_csv(OUTPUT_FILE, index=False)

    print(f"\n=== Timeline Metrics (Grouped by {FILTER_INTERVAL}s Intervals) ===")
    print(step_summary.to_string(index=False))

except FileNotFoundError as e:
    print(f"Error: Missing resource file. Details: {e}")
except KeyError as e:
    print(f"Error: Column mismatch or parsing issue. Details: {e}")