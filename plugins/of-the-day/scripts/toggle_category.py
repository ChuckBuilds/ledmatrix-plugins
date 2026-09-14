#!/usr/bin/env python3
"""
Toggle a category's enabled status.
Receives category_name and optional enabled state via stdin as JSON.
"""

import os
import json
import sys
from pathlib import Path

LEDMATRIX_ROOT = os.environ.get('LEDMATRIX_ROOT', os.getcwd())
config_file = Path(LEDMATRIX_ROOT) / 'config' / 'config.json'

# Read params from stdin
try:
    stdin_input = sys.stdin.read().strip()
    if stdin_input:
        params = json.loads(stdin_input)
    else:
        params = {}
except (json.JSONDecodeError, ValueError) as e:
    print(json.dumps({
        'status': 'error',
        'message': f'Invalid JSON input: {str(e)}'
    }))
    sys.exit(1)

category_name = params.get('category_name')
if not category_name:
    print(json.dumps({
        'status': 'error',
        'message': 'category_name is required'
    }))
    sys.exit(1)

# Load current config
config = {}
try:
    if config_file.exists():
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
except (json.JSONDecodeError, ValueError) as e:
    print(json.dumps({
        'status': 'error',
        'message': f'Failed to load config: {str(e)}'
    }))
    sys.exit(1)

# Get plugin config
plugin_config = config.get('of-the-day', {})
categories = plugin_config.get('categories', {})

# A data file with no config entry is listed as enabled by list_files.py and
# shown by the plugin, so toggling it must create the entry rather than fail.
if category_name not in categories:
    data_file = Path(__file__).parent.parent / 'of_the_day' / f'{category_name}.json'
    if not data_file.is_file():
        print(json.dumps({
            'status': 'error',
            'message': f'Category "{category_name}" not found in config or of_the_day/'
        }))
        sys.exit(1)
    categories[category_name] = {
        'enabled': True,
        'data_file': f'of_the_day/{category_name}.json',
        'display_name': category_name.replace('_', ' ').title()
    }

# Determine new enabled state
if 'enabled' in params:
    # Explicit state provided
    new_enabled = bool(params['enabled'])
else:
    # Toggle current state
    current_enabled = categories[category_name].get('enabled', True)
    new_enabled = not current_enabled

# Update the category
categories[category_name]['enabled'] = new_enabled
plugin_config['categories'] = categories
config['of-the-day'] = plugin_config

# Save config
try:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
except Exception as e:
    print(json.dumps({
        'status': 'error',
        'message': f'Failed to save config: {str(e)}'
    }))
    sys.exit(1)

print(json.dumps({
    'status': 'success',
    'message': f'Category "{category_name}" {"enabled" if new_enabled else "disabled"}',
    'category_name': category_name,
    'enabled': new_enabled
}))
