#!/usr/bin/env python3
import csv
import re
from pathlib import Path

try:
    from PyPDF2 import PdfReader
except ImportError:
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2"])
    from PyPDF2 import PdfReader

def extract_bookmarks(pdf_path, csv_output_path):
    """Extract bookmarks from PDF and save to CSV without leading numbers."""
    
    # Read PDF
    pdf_reader = PdfReader(pdf_path)
    bookmarks = pdf_reader.outline
    
    # Extract bookmark names
    bookmark_names = []
    
    def process_bookmarks(bookmarks_list, level=0):
        for bookmark in bookmarks_list:
            if isinstance(bookmark, dict):
                # It's a nested bookmark section
                if "/Title" in bookmark:
                    title = bookmark["/Title"]
                    # Remove leading numbers and spaces
                    cleaned_title = re.sub(r'^\d+\s*\.?\s*', '', title).strip()
                    if cleaned_title:
                        bookmark_names.append(cleaned_title)
                # Process nested bookmarks if they exist
                if isinstance(bookmark, list):
                    process_bookmarks(bookmark, level + 1)
            else:
                # It's a PdfObject with potential children
                if hasattr(bookmark, "title"):
                    title = bookmark.title
                    # Remove leading numbers and spaces
                    cleaned_title = re.sub(r'^\d+\s*\.?\s*', '', title).strip()
                    if cleaned_title:
                        bookmark_names.append(cleaned_title)
                if hasattr(bookmark, "__iter__"):
                    try:
                        process_bookmarks(list(bookmark), level + 1)
                    except:
                        pass
    
    # Handle the outline structure
    if isinstance(bookmarks, list):
        for bookmark in bookmarks:
            if hasattr(bookmark, "title"):
                title = bookmark.title
                cleaned_title = re.sub(r'^\d+\s*\.?\s*', '', title).strip()
                if cleaned_title:
                    bookmark_names.append(cleaned_title)
            if hasattr(bookmark, "__getitem__"):
                try:
                    for sub_bookmark in bookmark:
                        if hasattr(sub_bookmark, "title"):
                            title = sub_bookmark.title
                            cleaned_title = re.sub(r'^\d+\s*\.?\s*', '', title).strip()
                            if cleaned_title:
                                bookmark_names.append(cleaned_title)
                except:
                    pass
    
    # Write to CSV without quotes
    with open(csv_output_path, 'w', encoding='utf-8') as csvfile:
        csvfile.write('bookmark\n')
        for name in bookmark_names:
            csvfile.write(f'{name}\n')
    
    print(f"Extracted {len(bookmark_names)} bookmarks to {csv_output_path}")
    return bookmark_names

if __name__ == "__main__":
    # Define paths
    extract_towns_dir = Path(__file__).parent / "extract towns"
    pdf_path = extract_towns_dir / "HG06_04_merged_q20.pdf"
    csv_path = extract_towns_dir / "HG06_04_bookmarks.csv"
    
    if not pdf_path.exists():
        print(f"PDF file not found: {pdf_path}")
        exit(1)
    
    bookmarks = extract_bookmarks(str(pdf_path), str(csv_path))
    print(f"\nFirst 10 bookmarks:")
    for name in bookmarks[:10]:
        print(f"  - {name}")
