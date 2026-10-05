import pandas as pd
import sys

def main():
    csv_file = "results_raw.csv"
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]

    try:
        # Read the raw Sightglass CSV file
        df = pd.read_csv(csv_file)
    except FileNotFoundError:
        print(f"Error: The file '{csv_file}' was not found.")
        print("Please ensure you run your benchmark with: ... > raw_results.csv")
        return

    # Clean up the 'wasm' column path (e.g., 'benchmarks/hashset/benchmark.wasm' -> 'hashset')
    df['benchmark'] = df['wasm'].apply(lambda x: x.split('/')[1] if '/' in str(x) else x)

    # Filter by event type just in case you sample other hardware counters in the future
    df_cycles = df[df['event'] == 'cycles']

    # Group by benchmark and phase, then aggregate statistics over the 'count' column
    stats = df_cycles.groupby(['benchmark', 'phase'])['count'].agg(['min', 'mean', 'std', 'max']).reset_index()

    # Round floating-point averages and standard deviations for cleaner output
    stats['mean'] = stats['mean'].round(2)
    stats['std'] = stats['std'].round(2)

    # Rename columns to look professional for your data analysis
    stats.columns = ['Benchmark', 'Phase', 'Min (Cycles)', 'Mean (Cycles)', 'Std Dev (Cycles)', 'Max (Cycles)']

    # Print out a nicely formatted plaintext table
    print("\n=========================================================================")
    print("           Sightglass Statistical Summary (with Standard Deviation)      ")
    print("=========================================================================")
    print(stats.to_string(index=False))
    print("=========================================================================\n")

if __name__ == "__main__":
    main()
