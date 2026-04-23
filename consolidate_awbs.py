#!/usr/bin/env python3
"""Add AWB consolidation logic to deduplicate by number"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
pdf_upload_path = PROJECT_ROOT / "app" / "ui" / "pages" / "pdf_upload.py"

print("Adding AWB consolidation function to pdf_upload.py...")

# Read current file
current_code = pdf_upload_path.read_text(encoding='utf-8')

# Find the import section and add the consolidation function after ICargoIBSClient
insert_point = current_code.find("class ICargoIBSClient:")
if insert_point == -1:
    print("ERROR: Could not find ICargoIBSClient in pdf_upload.py")
    exit(1)

# Find the end of ICargoIBSClient class (next def or comment at column 0)
class_end = current_code.find("\n\n\n# =========", insert_point)
if class_end == -1:
    class_end = current_code.find("\ndef render_pdf_upload", insert_point)

consolidation_function = '''

# =========================================================
# AWB Consolidation: Merge duplicate AWB numbers
# =========================================================
def consolidate_awbs_by_number(normalized_awbs):
    """
    Consolidate multiple AWB entries with the same number into single entries.
    
    If the same AWB number appears multiple times (e.g., on different PDF pages),
    merge them into one consolidated record, preferring non-None values.
    
    Args:
        normalized_awbs: List of AwbData objects
    
    Returns:
        List of deduplicated AwbData (one per unique AWB number)
    """
    from collections import defaultdict
    
    # Group by AWB number
    awb_groups = defaultdict(list)
    for awb in normalized_awbs:
        key = awb.awb_number or "NO_NUMBER"
        awb_groups[key].append(awb)
    
    # Consolidate each group
    consolidated = []
    for awb_number, awbs in awb_groups.items():
        if len(awbs) == 1:
            # Single occurrence, keep as-is
            consolidated.append(awbs[0])
        else:
            # Multiple occurrences: merge, preferring non-None values
            merged = awbs[0].copy(deep=True)  # Start with first
            
            for awb in awbs[1:]:
                # Merge fields: prefer non-None values from this AWB
                for field in awb.__fields__.keys():
                    current_val = getattr(merged, field)
                    new_val = getattr(awb, field)
                    
                    # Prefer non-None value from new_val, otherwise keep current
                    if new_val is not None:
                        setattr(merged, field, new_val)
            
            consolidated.append(merged)
    
    return consolidated

'''

# Insert the function before render_pdf_upload
new_code = current_code[:class_end] + consolidation_function + current_code[class_end:]

# Now find where we filter by 233 and add consolidation call
filter_point = new_code.find("# FILTER: Keep only AWB with prefix 233")
if filter_point != -1:
    # Find the line where we create filtered_awbs
    filter_line_start = new_code.find("filtered_awbs = [awb for awb in", filter_point)
    filter_line_end = new_code.find("\n", filter_line_start)
    
    if filter_line_start != -1:
        # Replace the filter line to add consolidation
        old_filter = new_code[filter_line_start:filter_line_end]
        new_filter = "filtered_awbs = consolidate_awbs_by_number([awb for awb in normalized_awbs if awb.awb_prefix == \"233\"])"
        new_code = new_code[:filter_line_start] + new_filter + new_code[filter_line_end:]

# Write back
pdf_upload_path.write_text(new_code, encoding='utf-8')

print("✅ SUCCESS! Added consolidation function")
print("\nWhat it does:")
print("  1. Groups AWBs by number (233-XXXXXXXX)")
print("  2. If same number appears multiple times:")
print("     - Merges all occurrences into ONE record")
print("     - Uses non-None values from all occurrences")
print("  3. Result: Only unique AWB numbers in the UI")
print("\nExample:")
print("  Before: [AWB 233-12345678 (page1), AWB 233-12345678 (page2), AWB 233-87654321 (page3)]")
print("  After:  [AWB 233-12345678 (merged), AWB 233-87654321]")