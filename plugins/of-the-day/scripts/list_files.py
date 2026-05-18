#!/usr/bin/env python3
"""
List all JSON data files in the of_the_day directory.
Returns file metadata including entry count, size, modification time, and enabled status.
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime

# Get plugin directory (scripts/ -> plugin root)
plugin_dir = Path(__file__).parent.parent
data_dir = plugin_dir / 'of_the_day'
LEDMATRIX_ROOT = os.environ.get('LEDMATRIX_ROOT', os.getcwd())
config_file = Path(LEDMATRIX_ROOT) / 'config' / 'config.json'

# Read params from stdin if provided (optional for this script)
try:
    stdin_input = sys.stdin.read().strip()
    if stdin_input:
        params = json.loads(stdin_input)
except (json.JSONDecodeError, ValueError):
    # No params or invalid JSON, continue without params
    params = {}

# Load config to get enabled status for each category
config = {}
try:
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
except (json.JSONDecodeError, ValueError):
    config = {}

# Get plugin categories config
plugin_config = config.get('of-the-day', {})
categories_config = plugin_config.get('categories', {})

if not data_dir.exists():
    print(json.dumps({
        'status': 'success',
        'files': []
    }))
    sys.exit(0)

files = []
for file_path in data_dir.glob('*.json'):
    try:
        # Get file stats
        stat = file_path.stat()

        # Read and parse JSON to count entries
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            entry_count = len(data) if isinstance(data, dict) else 0

        # Extract category name from filename
        category_name = file_path.stem

        # Get enabled status from config (default to True if not in config)
        category_config = categories_config.get(category_name, {})
        enabled = category_config.get('enabled', True)
        display_name = category_config.get('display_name', category_name.replace('_', ' ').title())

        files.append({
            'filename': file_path.name,
            'category_name': category_name,
            'display_name': display_name,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'entry_count': entry_count,
            'enabled': enabled
        })
    except Exception:
        # Skip files that can't be read
        continue

# Sort by filename
files.sort(key=lambda x: x['filename'])

print(json.dumps({
    'status': 'success',
    'files': files
}))

