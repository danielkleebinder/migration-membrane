import csv
import statistics
import os

# =====================================================================
# CONFIGURATION
# =====================================================================
# Dictionary mapping the friendly name (key) to the CSV file path (value)
CSV_FILES = {
    "14ms SLO Baseline": "experiment-results/14ms900s/14ms_900s_migration_tax.csv",
    "10ms SLO Target": "experiment-results/10ms900s/10ms_900s_migration_tax.csv",
    "6ms SLO Strict": "experiment-results/6ms900s/6ms_900s_migration_tax.csv"
}

# The name of the new CSV file to export the medians to
OUTPUT_CSV_FILE = "migration_tax_medians.csv"

# The columns we want to calculate the median for
TARGET_COLUMNS = [
    "migration_time",
    "source_duration",
    "downtime",
    "host_window",
    "migration_tax",
    "events"
]


def calculate_medians(files_dict):
    results = {}

    for name, filepath in files_dict.items():
        if not os.path.exists(filepath):
            print(f"[Warning] File not found, skipping: {filepath}")
            continue

        # Initialize lists to hold the parsed numeric data
        column_data = {col: [] for col in TARGET_COLUMNS}

        with open(filepath, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                for col in TARGET_COLUMNS:
                    val = row.get(col, "N/A").strip()

                    # Safely parse numeric values, ignoring "N/A" or empty strings
                    if val != "N/A" and val != "":
                        try:
                            column_data[col].append(float(val))
                        except ValueError:
                            pass  # Skip unparseable data

        # Calculate the median for each column
        medians = {}
        for col in TARGET_COLUMNS:
            if column_data[col]:
                medians[col] = statistics.median(column_data[col])
            else:
                medians[col] = None  # No valid data found for this column

        results[name] = medians

    return results


def print_summary_table(results):
    if not results:
        print("No data to display.")
        return

    # Print Table Header
    header = (
        f"{'Experiment / Name':<20} | {'Mig. Time':<10} | {'Src Dur.':<10} | "
        f"{'Downtime':<10} | {'Host Win':<10} | {'Mig Tax':<10} | {'Events'}"
    )
    print("\n" + "=" * len(header))
    print(header)
    print("-" * len(header))

    # Print Table Rows
    for name, medians in results.items():
        # Helper to format floats to 3 decimal places, or print "N/A"
        def fmt(val):
            return f"{val:<10.3f}" if val is not None else f"{'N/A':<10}"

        row_str = (
            f"{name:<20} | {fmt(medians['migration_time'])} | {fmt(medians['source_duration'])} | "
            f"{fmt(medians['downtime'])} | {fmt(medians['host_window'])} | {fmt(medians['migration_tax'])} | "
            f"{medians['events'] if medians['events'] is not None else 'N/A'}"
        )
        print(row_str)

    print("=" * len(header) + "\n")


def export_summary_to_csv(results, output_filepath):
    if not results:
        return

    # Define the CSV header
    header = ["experiment", "migration_time", "source_duration", "downtime", "host_window", "migration_tax", "events"]

    with open(output_filepath, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for name, medians in results.items():
            # Helper to round floats to 3 decimal places, or return "N/A"
            def fmt(val):
                return round(val, 3) if val is not None else "N/A"

            # Format events (usually an integer, but could be a .5 float if the dataset is an even number)
            events_val = medians['events']
            if events_val is not None:
                events_val = int(events_val) if events_val.is_integer() else round(events_val, 3)
            else:
                events_val = "N/A"

            row = [
                name,
                fmt(medians['migration_time']),
                fmt(medians['source_duration']),
                fmt(medians['downtime']),
                fmt(medians['host_window']),
                fmt(medians['migration_tax']),
                events_val
            ]
            writer.writerow(row)

    print(f"[Success] Median data exported to: {output_filepath}")


if __name__ == "__main__":
    # 1. Run the actual calculation
    computed_medians = calculate_medians(CSV_FILES)

    # 2. Print the results to the console
    print_summary_table(computed_medians)

    # 3. Export the results to a CSV file
    export_summary_to_csv(computed_medians, OUTPUT_CSV_FILE)