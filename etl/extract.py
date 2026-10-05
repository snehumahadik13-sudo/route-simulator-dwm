import csv
import hashlib
from pathlib import Path
from typing import Generator, Dict, Any, Tuple
from .config import DATA_DIR, FILES

def compute_file_hash(filepath: Path) -> str:
    """Computes SHA-256 hash of a file for integrity and deduplication checks."""
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def verify_and_deduplicate_sources() -> Dict[str, Path]:
    """
    Scans data directory, verifies required source files, and detects duplicate files.
    Specifically skips identical duplicate download 'indian_roads_dataset (2).csv'.
    """
    valid_files = {}
    hashes_seen = {}
    
    print("\n--- Verifying & Validating Source Datasets ---")
    for key, filename in FILES.items():
        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"[WARNING] Expected source file not found: {filename}")
            continue
            
        fhash = compute_file_hash(filepath)
        size_mb = filepath.stat().st_size / (1024 * 1024)
        
        if fhash in hashes_seen:
            orig_key, orig_name = hashes_seen[fhash]
            print(f"[DEDUPLICATION] Skipping '{filename}' - Exact binary duplicate of '{orig_name}' (SHA256: {fhash[:12]}...)")
            continue
            
        hashes_seen[fhash] = (key, filename)
        valid_files[key] = filepath
        print(f"[FOUND] {filename:<36} | {size_mb:>6.2f} MB | SHA256: {fhash[:12]}...")
        
    print("---------------------------------------------\n")
    return valid_files

def extract_csv_rows(filepath: Path) -> Generator[Dict[str, str], None, None]:
    """
    Streams CSV rows as dictionaries with stripped whitespace in headers and values.
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return
            
        clean_header = [col.strip() for col in header]
        
        for row in reader:
            if not row:
                continue
            # Map header to row values
            row_dict = {}
            for idx, col in enumerate(clean_header):
                val = row[idx].strip() if idx < len(row) else ""
                row_dict[col] = val
            yield row_dict
