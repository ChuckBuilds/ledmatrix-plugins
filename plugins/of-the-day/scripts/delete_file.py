#!/usr/bin/env python3
"""
Delete a JSON file from the of_the_day directory.
Also removes the category from plugin configuration.
"""

import json
import sys
from pathlib import Path

# Get plugin directory (scripts/ -> plugin root)
plugin_dir = Path(__file__).parent.parent
data_dir = plugin_dir / 'of_the_day'

try:
    input_data = json.load(sys.stdin)
    filename = input_data.get('filename', '')
    
    if not filename:
        print(json.dumps({
            'status': 'error',
            'message': 'Filename is required'
        }))
        sys.exit(1)
    
    # Security: ensure filename doesn't contain path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        print(json.dumps({
            'status': 'error',
            'message': 'Invalid filename'
        }))
        sys.exit(1)
    
    file_path = data_dir / filename
    
    if not file_path.exists():
        print(json.dumps({
            'status': 'error',
            'message': f'File {filename} not found'
        }))
        sys.exit(1)
    
    # Extract category name
    category_name = filename.replace('.json', '')
    
    # Delete file
    file_path.unlink()
    
    # Remove from config
    sys.path.insert(0, str(plugin_dir))
    from scripts.update_config import remove_category_from_config
    remove_category_from_config(category_name)
    
    print(json.dumps({
        'status': 'success',
        'message': f'File {filename} deleted successfully'
    }))
    
except Exception as e:
    print(json.dumps({
        'status': 'error',
        'message': str(e)
    }))
    sys.exit(1)

