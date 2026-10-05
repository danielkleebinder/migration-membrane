import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os

# --- Configuration ---
FILTER_INTERVAL = 0.2  # 200 ms bins on X-axis
BASE_RUNS_DIR = 'runs/multi/stop-copy'
NUM_ITERATIONS = 20
OUTPUT_FILENAME = 'postcopy_heatmap.pdf'  # Export as PDF for vector quality

# --- Column Mappings ---
COL_TIME = 'Time'
COL_LATENCY = 'Latency'

# --- Custom Academic Color Palette ---
# Light Gray for 0% loss, morphing to deep red for 100% loss blackout
# 'Greys' or 'Reds' can also be used.
from matplotlib.colors import LinearSegmentedColormap

# Define the gradient from light gray (0% loss) to deep red (100% loss)
colors = ["#f7f7f7", "#fee0d2", "#fc9272", "#de2d26", "#a50f15"]
cmap = LinearSegmentedColormap.from_list("custom_reds", colors)


def main():
    print(f"Creating Post-Copy Heatmap from {NUM_ITERATIONS} iterations.")
    print(f"Time Bins: {FILTER_INTERVAL}s")

    # This list will hold the 1D time-series data for each iteration
    iteration_data_series = []

    # 1. Loop through all raw files for the post-copy strategy
    for i in range(1, NUM_ITERATIONS + 1):
        file_path = os.path.join(BASE_RUNS_DIR, f'results_it{i}.csv')

        if os.path.exists(file_path):
            df = pd.read_csv(file_path, dtype={'Address': str})

            # Convert raw Time column to numeric
            df[COL_TIME] = pd.to_numeric(df[COL_TIME], errors='coerce')

            # Identify Lost Packets (Latency is NaN)
            df['lost'] = df[COL_LATENCY].isna().astype(int)

            # Bin data into 200ms steps based on FILTER_INTERVAL
            df['step'] = np.round((df[COL_TIME] // FILTER_INTERVAL) * FILTER_INTERVAL, 3)

            # Aggregate: Count total rows (sent) and lost rows per bin for THIS iteration
            binned = df.groupby('step').agg(
                lost=('lost', 'sum'),
                sent=('lost', 'count')  # Assuming every row is 1 sent packet
            ).reset_index()

            # Calculate Packet Loss Percentage bounded 0-100%
            # Handle possible div by zero if sent count is 0 (though unlikely)
            binned['lost_pct'] = (binned['lost'] / binned['sent']).fillna(0) * 100.0

            # Keep only the necessary columns (step and lost_pct) and ensure sorting
            binned = binned[['step', 'lost_pct']].sort_values('step')

            # Rename 'lost_pct' column to the specific iteration number
            binned = binned.set_index('step')
            binned.rename(columns={'lost_pct': i}, inplace=True)

            iteration_data_series.append(binned)
        else:
            print(f"  Warning: {file_path} not found. Skipping...")

    if not iteration_data_series:
        raise ValueError("[Error] No valid iteration files were found.")

    # 2. Merge all 1D series on the 'step' column to create the 2D matrix
    # We start with a base step range covering the whole experiment duration
    final_pivot = pd.concat(iteration_data_series, axis=1)

    # Fill any time bins where data didn't exist with 0% loss (normal operation)
    final_pivot.fillna(0, inplace=True)

    # Transpose the data: Rows = Iteration, Columns = Time Step
    heatmap_matrix = final_pivot.transpose()

    # Ensure iteration index is strictly integers
    heatmap_matrix.index = heatmap_matrix.index.astype(int)

    # 3. Plotting using Matplotlib and Seaborn
    print("\nGenerating heatmap visualization...")

    # Set figure size appropriate for a single-column width in a paper
    plt.figure(figsize=(8, 4.5))

    # Configure heatmap appearance
    ax = sns.heatmap(
        heatmap_matrix,
        cmap=cmap,  # Custom red gradient
        vmin=0, vmax=100,  # Force color bounds 0% to 100%
        cbar_kws={'label': 'Packet Loss (%)'},  # Label for color legend
        rasterized=True  # Speeds up PDF rendering by flattening pixels
    )

    # Adjust axes formatting
    plt.title("Post-Copy Multi-Iteration Packet Loss Profile", fontsize=12)
    plt.xlabel("Time (seconds)", fontsize=10)
    plt.ylabel("Iteration Number", fontsize=10)

    # Customize ticks on the X-axis for better readability (show only every ~5s)
    x_ticks_step = 25  # number of columns (200ms steps) to skip, 25 * 0.2s = 5s
    # ax.set_xticks() doesn't work directly with seaborn.heatmap's custom index labels
    for i, label in enumerate(ax.get_xticklabels()):
        if i % x_ticks_step == 0:
            label.set_visible(True)
        else:
            label.set_visible(False)

    plt.tight_layout()

    # 4. Save figure as high-resolution PDF/PNG
    plt.savefig(OUTPUT_FILENAME, dpi=300)
    print(f"Heatmap successfully saved to {OUTPUT_FILENAME}")

    # Optional: Close plot to free memory if running in a loop
    plt.close()


if __name__ == "__main__":
    main()