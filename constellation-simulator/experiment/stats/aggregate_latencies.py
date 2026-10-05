import pandas as pd
import numpy as np

def aggregate_latencies(input_csv="experiment/results.csv", output_csv="experiment-results/latencies.csv", bin_size_ms=2000):
    print(f"Loading '{input_csv}'...")
    try:
        df = pd.read_csv(input_csv)
    except FileNotFoundError:
        print(f"[Error] Could not find {input_csv}. Make sure the experiment has run and results were fetched.")
        return

    # Clean and convert columns
    df = df.dropna(subset=['Latency', 'Time'])
    df['Latency'] = pd.to_numeric(df['Latency'], errors='coerce')
    df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
    df = df.dropna()

    # Convert bin size from milliseconds to seconds
    bin_size_sec = bin_size_ms / 1000.0

    # Assign each packet to its time bin
    df['step'] = (df['Time'] // bin_size_sec) * bin_size_sec

    # Group by the time bin and compute statistics using NumPy percentiles
    print(f"Calculating median, p5, and p95 per {bin_size_ms}ms interval...")
    aggregated = df.groupby('step')['Latency'].agg(
        median=lambda x: np.percentile(x, 50),
        p5=lambda x: np.percentile(x, 10),
        p95=lambda x: np.percentile(x, 90),
        packet_count='count'
    ).reset_index()

    # Format output for readability
    aggregated['step'] = aggregated['step'].round(3)
    aggregated[['median', 'p5', 'p95']] = aggregated[['median', 'p5', 'p95']].round(4)

    # Save to CSV
    aggregated.to_csv(output_csv, index=False)
    print(f"Successfully saved aggregated metrics to '{output_csv}'")
    print(aggregated.head(10))

if __name__ == "__main__":
    aggregate_latencies()