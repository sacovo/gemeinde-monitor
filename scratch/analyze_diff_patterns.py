import os
import glob
from collections import Counter

diff_files = glob.glob("monitor_changes/*.diff")
print(f"Analyzing {len(diff_files)} diff files...\n")

additions = []
deletions = []
diff_lines = []

for filepath in diff_files:
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        lines = content.splitlines()
        
        # Print a short summary of each file's changes
        print(f"=== File: {os.path.basename(filepath)} ===")
        # Get the URL line (first line usually)
        url_line = next((l for l in lines if l.startswith("URL:")), "Unknown URL")
        print(url_line)
        
        change_lines = []
        for line in lines:
            if line.startswith('+') and not line.startswith('+++') and not line.startswith('+++ current_state'):
                additions.append(line[1:])
                change_lines.append(line)
            elif line.startswith('-') and not line.startswith('---') and not line.startswith('--- previous_state'):
                deletions.append(line[1:])
                change_lines.append(line)
        
        # Print up to 10 lines of changes
        for l in change_lines[:10]:
            print(f"  {l}")
        if len(change_lines) > 10:
            print(f"  ... and {len(change_lines) - 10} more lines of changes.")
        print()

# Count common words or exact lines
print("=== Top 15 Most Common Added Lines ===")
for line, count in Counter(additions).most_common(15):
    print(f"({count}x) {line}")

print("\n=== Top 15 Most Common Deleted Lines ===")
for line, count in Counter(deletions).most_common(15):
    print(f"({count}x) {line}")
