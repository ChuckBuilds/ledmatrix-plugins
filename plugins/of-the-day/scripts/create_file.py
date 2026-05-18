#!/usr/bin/env python3
"""
Create a new JSON file with template structure (365 empty entries).
Automatically adds category to config.
"""

import json
import sys
from pathlib import Path

# Get plugin directory (scripts/ -> plugin root)
plugin_dir = Path(__file__).parent.parent
data_dir = plugin_dir / 'of_the_day'
data_dir.mkdir(parents=True, exist_ok=True)

try:
    input_data = json.load(sys.stdin)
    category_name = input_data.get('category_name', '').strip()
    display_name = input_data.get('display_name', category_name.replace('_', ' ').title() if category_name else '')
    
    if not category_name:
        print(json.dumps({
            'status': 'error',
            'message': 'Category name is required'
        }))
        sys.exit(1)
    
    # Validate category name (alphanumeric + underscores)
    if not category_name.replace('_', '').isalnum():
        print(json.dumps({
            'status': 'error',
            'message': 'Category name must contain only letters, numbers, and underscores'
        }))
        sys.exit(1)
    
    filename = f"{category_name}.json"
    file_path = data_dir / filename
    
    # Check if file already exists
    if file_path.exists():
        print(json.dumps({
            'status': 'error',
            'message': f'File {filename} already exists'
        }))
        sys.exit(1)
    
    # Create template with 365 empty entries
    template = {}
    for day in range(1, 366):  # 1-365
        template[str(day)] = {
            'title': '',
            'subtitle': '',
            'description': ''
        }
    
    # Save file
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, indent=2, ensure_ascii=False)
    
    # Update config
    sys.path.insert(0, str(plugin_dir))
    from scripts.update_config import add_category_to_config
    add_category_to_config(category_name, f'of_the_day/{filename}', display_name)
    
    print(json.dumps({
        'status': 'success',
        'message': f'File {filename} created successfully',
        'filename': filename,
        'category_name': category_name
    }))
    
except Exception as e:
    print(json.dumps({
        'status': 'error',
        'message': str(e)
    }))
    sys.exit(1)

