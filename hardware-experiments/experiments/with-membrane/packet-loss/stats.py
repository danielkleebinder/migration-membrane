import pandas as pd
import numpy as np
import os

# --- Configuration ---
FILTER_INTERVAL = 0.2
BASE_RUNS_DIR = 'runs/multi'
STRATEGIES = ['membrane', 'post-copy', 'pre-copy', 'stop-copy']
OUTPUT_BASE_NAME = 'packet_loss_results'

# --- Column Mappings ---
COL_TIME = 'Time'
COL_LATENCY = 'Latency'


def main():
    print(f"Starting analysis. Bins: {FILTER_INTERVAL}s")

    for strategy in STRATEGIES:
        runs_dir = os.path.join(BASE_RUNS_DIR, strategy)
        print(f"\n--- Processing strategy: {strategy} ---")

        all_runs = []

        # 1. Read all 20 files from the strategy directory
        for i in range(1, 21):
            file_path = os.path.join(runs_dir, f'results_it{i}.csv')
            if os.path.exists(file_path):
                # Added dtype={'Address': str} to fix the DtypeWarning
                df = pd.read_csv(file_path, dtype={'Address': str})
                df['iteration'] = i
                all_runs.append(df)
            else:
                print(f"  Warning: {file_path} not found. Skipping...")

        if not all_runs:
            print(f"  [!] No CSV files found for {strategy}. Skipping.")
            continue

        # Combine into one massive DataFrame for this strategy
        df_raw = pd.concat(all_runs, ignore_index=True)

        # Convert Time and Latency to numeric (forces errors/blanks to NaN)
        df_raw[COL_TIME] = pd.to_numeric(df_raw[COL_TIME], errors='coerce')
        df_raw[COL_LATENCY] = pd.to_numeric(df_raw[COL_LATENCY], errors='coerce')

        # Every row in the CSV is 1 sent packet
        df_raw['sent'] = 1
        # If Latency is NaN, the packet was lost (1). Otherwise, 0.
        df_raw['lost'] = df_raw[COL_LATENCY].isna().astype(int)

        # 2. Create the time bins (step)
        # Added np.round(..., 3) to prevent floating-point drift (e.g., 0.40000000000001)
        df_raw['step'] = np.round((df_raw[COL_TIME] // FILTER_INTERVAL) * FILTER_INTERVAL, 3)

        # 3. Aggregate WITHIN each iteration
        run_binned = df_raw.groupby(['iteration', 'step']).agg(
            lost=('lost', 'sum'),
            sent=('sent', 'sum'),
            latency=(COL_LATENCY, 'median')  # Median latency of packets that arrived
        ).reset_index()

        # 4. Aggregate ACROSS all iterations (Added Latency p5 and p95)
        final_stats = run_binned.groupby('step').agg(
            lost_p50=('lost', lambda x: np.percentile(x, 50)),
            lost_p5=('lost', lambda x: np.percentile(x, 5)),
            lost_p95=('lost', lambda x: np.percentile(x, 95)),
            sent=('sent', lambda x: np.percentile(x, 50)),
            latency_p50=('latency', lambda x: np.percentile(x.dropna(), 50) if not x.dropna().empty else 0),
            latency_p5=('latency', lambda x: np.percentile(x.dropna(), 5) if not x.dropna().empty else 0),
            latency_p95=('latency', lambda x: np.percentile(x.dropna(), 95) if not x.dropna().empty else 0)
        ).reset_index()

        # Clean up any NaN values
        final_stats.fillna(0, inplace=True)

        # Rename columns to include the strategy name (except for 'step')
        strat_prefix = strategy.replace('-', '')
        rename_dict = {col: f"{col}" for col in final_stats.columns if col != 'step'}
        final_stats.rename(columns=rename_dict, inplace=True)

        # --- Round all columns to at most 3 decimal places ---
        final_stats = final_stats.round(3)

        # 5. Export to individual CSV for this strategy
        # Creates files like: packet_loss_results_membrane.csv, packet_loss_results_post-copy.csv
        output_file = f"{OUTPUT_BASE_NAME}_{strat_prefix}.csv"
        final_stats.to_csv(output_file, index=False)
        print(f"  Success! Data exported to {output_file}")


if __name__ == "__main__":
    main()