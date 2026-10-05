import pandas as pd
import numpy as np
import os

BASE_RUNS_DIR = 'runs/multi'
STRATEGIES = ['membrane', 'post-copy', 'pre-copy', 'stop-copy']
COL_LATENCY = 'Latency'


def main():
    for strategy in STRATEGIES:
        runs_dir = os.path.join(BASE_RUNS_DIR, strategy)
        lost_percentages = []

        # Read all iterations and get loss per 200ms bin
        for i in range(1, 21):
            file_path = os.path.join(runs_dir, f'results_it{i}.csv')
            if os.path.exists(file_path):
                df = pd.read_csv(file_path, dtype={'Address': str})
                df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
                df['lost'] = df[COL_LATENCY].isna().astype(int)
                df['step'] = np.round((df['Time'] // 0.2) * 0.2, 3)

                binned = df.groupby('step').agg(
                    lost=('lost', 'sum'),
                    sent=('lost', 'count')
                )
                binned['lost_pct'] = (binned['lost'] / binned['sent']) * 100.0
                lost_percentages.extend(binned['lost_pct'].tolist())

        if not lost_percentages:
            continue

        # Compute empirical CDF
        sorted_data = np.sort(lost_percentages)
        cdf = np.arange(1, len(sorted_data) + 1) / len(sorted_data)

        # Create DataFrame and round
        df_cdf = pd.DataFrame({'lost_pct': sorted_data, 'cdf': cdf}).round(4)

        # Deduplicate to shrink CSV size for TikZ
        df_cdf = df_cdf.groupby('lost_pct').max().reset_index()

        strat_prefix = strategy.replace('-', '')
        output_file = f'cdf_{strat_prefix}.csv'
        df_cdf.to_csv(output_file, index=False)
        print(f"Exported CDF to {output_file}")


if __name__ == "__main__":
    main()