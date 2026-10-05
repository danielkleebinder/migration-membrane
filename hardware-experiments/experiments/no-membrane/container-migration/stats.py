import pandas as pd
import os

def process_stats():
    input_file = 'results_container_migration.csv'
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    # Load the dataset
    df = pd.read_csv(input_file)

    # Sanitize 'load' column: remove '%' and 'MB'
    df['load'] = df['load'].str.replace('%', '', regex=False).str.replace('MB', '', regex=False)
    
    # Convert load to numeric if possible, though it might be mixed
    df['load'] = pd.to_numeric(df['load'])

    # Columns to average
    avg_cols = ['checkpoint', 'sync', 'create', 'start', 'total']
    
    # Group by profile and load
    # Calculate mean for all relevant columns and std for 'total'
    grouped = df.groupby(['profile', 'load'])
    
    stats = grouped[avg_cols].mean().reset_index()
    std_total = grouped['total'].std().reset_index().rename(columns={'total': 'total_std'})
    
    # Merge mean and std
    final_df = pd.merge(stats, std_total, on=['profile', 'load'])

    # Profile mapping to filenames
    profiles = {
        'CPU': 'cpu.csv',
        'Memory': 'memory.csv',
        'Disk': 'disk.csv'
    }

    for profile_name, output_file in profiles.items():
        profile_df = final_df[final_df['profile'] == profile_name].copy()
        if not profile_df.empty:
            # Drop profile column as it's implied by the filename
            profile_df = profile_df.drop(columns=['profile'])
            profile_df.to_csv(output_file, index=False)
            print(f"Created {output_file}")
        else:
            print(f"No data for profile {profile_name}")

if __name__ == "__main__":
    process_stats()
