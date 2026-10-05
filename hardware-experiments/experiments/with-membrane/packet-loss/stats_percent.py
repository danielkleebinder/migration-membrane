import pandas as pd
import numpy as np
import os

# --- Configuration ---
FILTER_INTERVAL = 0.2  # 200 ms bins
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

        for i in range(1, 21):
            file_path = os.path.join(runs_dir, f'results_it{i}.csv')
            if os.path.exists(file_path):
                df = pd.read_csv(file_path, dtype={'Address': str})
                df['iteration'] = i
                all_runs.append(df)
            else:
                print(f"  Warning: {file_path} not found. Skipping...")

        if not all_runs:
            print(f"  [!] No CSV files found for {strategy}. Skipping.")
            continue

        df_raw = pd.concat(all_runs, ignore_index=True)

        df_raw[COL_TIME] = pd.to_numeric(df_raw[COL_TIME], errors='coerce')
        df_raw[COL_LATENCY] = pd.to_numeric(df_raw[COL_LATENCY], errors='coerce')

        df_raw['sent'] = 1
        df_raw['lost'] = df_raw[COL_LATENCY].isna().astype(int)

        df_raw['step'] = np.round((df_raw[COL_TIME] // FILTER_INTERVAL) * FILTER_INTERVAL, 3)

        # 1. Aggregate WITHIN each iteration
        run_binned = df_raw.groupby(['iteration', 'step']).agg(
            lost=('lost', 'sum'),
            sent=('sent', 'sum'),
            latency=(COL_LATENCY, 'median')
        ).reset_index()

        # Calculate packet loss percentage for each bin within the iteration
        run_binned['lost_pct'] = (run_binned['lost'] / run_binned['sent']) * 100.0

        # 2. Aggregate ACROSS all iterations (Percentiles in %)
        final_stats = run_binned.groupby('step').agg(
            lost_p50=('lost_pct', lambda x: np.percentile(x, 50)),
            lost_p5=('lost_pct', lambda x: np.percentile(x, 5)),
            lost_p95=('lost_pct', lambda x: np.percentile(x, 95)),
            sent=('sent', lambda x: np.percentile(x, 50)),
            latency_p50=('latency', lambda x: np.percentile(x.dropna(), 50) if not x.dropna().empty else 0),
            latency_p5=('latency', lambda x: np.percentile(x.dropna(), 5) if not x.dropna().empty else 0),
            latency_p95=('latency', lambda x: np.percentile(x.dropna(), 95) if not x.dropna().empty else 0)
        ).reset_index()

        final_stats.fillna(0, inplace=True)

        strat_prefix = strategy.replace('-', '')
        rename_dict = {col: f"{col}" for col in final_stats.columns if col != 'step'}
        final_stats.rename(columns=rename_dict, inplace=True)

        final_stats = final_stats.round(3)

        output_file = f"{OUTPUT_BASE_NAME}_{strat_prefix}.csv"
        final_stats.to_csv(output_file, index=False)
        print(f"  Success! Data exported to {output_file}")


if __name__ == "__main__":
    main()