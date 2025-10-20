#!/usr/bin/env python3
"""
Script to automatically update plugins.json with the latest versions from GitHub.
Checks each plugin's repository for new releases/tags and updates the registry.
"""

import json
import requests
import sys
import io
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import argparse

# Fix Windows encoding issues
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def get_github_releases(repo_url: str, github_token: Optional[str] = None) -> List[Dict]:
    """
    Fetch releases from a GitHub repository.
    
    Args:
        repo_url: Full GitHub repository URL
        github_token: Optional GitHub personal access token for higher rate limits
    
    Returns:
        List of release dictionaries
    """
    # Extract owner and repo from URL
    # e.g., "https://github.com/ChuckBuilds/ledmatrix-weather" -> "ChuckBuilds/ledmatrix-weather"
    parts = repo_url.rstrip('/').split('/')
    owner = parts[-2]
    repo = parts[-1]
    
    api_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    
    headers = {
        'Accept': 'application/vnd.github.v3+json'
    }
    
    if github_token:
        headers['Authorization'] = f'token {github_token}'
    
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not fetch releases for {repo}: {e}")
        return []


def get_github_tags(repo_url: str, github_token: Optional[str] = None) -> List[Dict]:
    """
    Fetch tags from a GitHub repository (fallback if no releases).
    
    Args:
        repo_url: Full GitHub repository URL
        github_token: Optional GitHub personal access token
    
    Returns:
        List of tag dictionaries
    """
    parts = repo_url.rstrip('/').split('/')
    owner = parts[-2]
    repo = parts[-1]
    
    api_url = f"https://api.github.com/repos/{owner}/{repo}/tags"
    
    headers = {
        'Accept': 'application/vnd.github.v3+json'
    }
    
    if github_token:
        headers['Authorization'] = f'token {github_token}'
    
    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Warning: Could not fetch tags for {repo}: {e}")
        return []


def parse_version(version_str: str) -> tuple:
    """
    Parse a version string into a comparable tuple.
    
    Args:
        version_str: Version string like "v1.0.0" or "1.0.0"
    
    Returns:
        Tuple of integers for comparison
    """
    # Remove 'v' prefix if present
    version_str = version_str.lstrip('v')
    
    try:
        parts = version_str.split('.')
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return (0, 0, 0)


def get_latest_version_from_github(repo_url: str, github_token: Optional[str] = None) -> Optional[Dict]:
    """
    Get the latest version information from GitHub.
    
    Args:
        repo_url: GitHub repository URL
        github_token: Optional GitHub token
    
    Returns:
        Dictionary with version info or None
    """
    # Try releases first
    releases = get_github_releases(repo_url, github_token)
    
    if releases:
        # Find the latest non-prerelease, non-draft release
        valid_releases = [r for r in releases if not r.get('draft') and not r.get('prerelease')]
        
        if valid_releases:
            latest = valid_releases[0]  # GitHub API returns newest first
            version = latest['tag_name'].lstrip('v')
            
            # Parse the published date
            published_date = datetime.fromisoformat(latest['published_at'].replace('Z', '+00:00'))
            
            return {
                'version': version,
                'released': published_date.strftime('%Y-%m-%d'),
                'tag_name': latest['tag_name']
            }
    
    # Fallback to tags if no releases
    tags = get_github_tags(repo_url, github_token)
    
    if tags:
        # Sort tags by version number
        sorted_tags = sorted(tags, key=lambda t: parse_version(t['name']), reverse=True)
        
        if sorted_tags:
            latest = sorted_tags[0]
            version = latest['name'].lstrip('v')
            
            return {
                'version': version,
                'released': datetime.now().strftime('%Y-%m-%d'),  # Use current date as fallback
                'tag_name': latest['name']
            }
    
    return None


def update_plugin_versions(registry_path: str = 'plugins.json', github_token: Optional[str] = None, dry_run: bool = False) -> bool:
    """
    Update the plugin registry with latest versions from GitHub.
    
    Args:
        registry_path: Path to plugins.json file
        github_token: Optional GitHub personal access token
        dry_run: If True, don't write changes, just show what would be updated
    
    Returns:
        True if updates were made, False otherwise
    """
    # Load the registry
    with open(registry_path, 'r', encoding='utf-8') as f:
        registry = json.load(f)
    
    updates_made = False
    
    print("Checking for plugin updates...\n")
    
    for plugin in registry['plugins']:
        plugin_id = plugin['id']
        plugin_name = plugin['name']
        repo_url = plugin['repo']
        current_latest = plugin.get('latest_version', 'unknown')
        
        print(f"Checking {plugin_name} ({plugin_id})...")
        print(f"  Current latest: {current_latest}")
        
        # Get latest version from GitHub
        latest_info = get_latest_version_from_github(repo_url, github_token)
        
        if not latest_info:
            print(f"  ⚠️  Could not fetch version info from GitHub")
            continue
        
        github_latest = latest_info['version']
        print(f"  GitHub latest: {github_latest}")
        
        # Compare versions
        if github_latest != current_latest:
            print(f"  ✨ Update available: {current_latest} → {github_latest}")
            
            if not dry_run:
                # Check if this version already exists in the versions list
                existing_versions = [v['version'] for v in plugin.get('versions', [])]
                
                if github_latest not in existing_versions:
                    # Add new version to the beginning of the versions list
                    new_version_entry = {
                        'version': github_latest,
                        'ledmatrix_min': plugin.get('versions', [{}])[0].get('ledmatrix_min', '2.0.0'),
                        'released': latest_info['released']
                    }
                    
                    plugin['versions'].insert(0, new_version_entry)
                    print(f"  ✅ Added version {github_latest} to versions list")
                
                # Update latest_version field
                plugin['latest_version'] = github_latest
                plugin['last_updated'] = latest_info['released']
                
                updates_made = True
        else:
            print(f"  ✓ Already up to date")
        
        print()
    
    if updates_made and not dry_run:
        # Write the updated registry
        with open(registry_path, 'w', encoding='utf-8') as f:
            json.dump(registry, f, indent=2, ensure_ascii=False)
        
        print(f"\n✅ Successfully updated {registry_path}")
        return True
    elif dry_run and updates_made:
        print("\n🔍 Dry run complete. Run without --dry-run to apply changes.")
        return False
    else:
        print("\n✓ All plugins are up to date!")
        return False


def load_github_token_from_config() -> Optional[str]:
    """
    Try to load GitHub token from config_secrets.json.
    
    Returns:
        GitHub token or None if not found
    """
    try:
        # Try multiple possible locations
        possible_paths = [
            Path(__file__).parent / "config_secrets.json",  # Local to this repo
            Path(__file__).parent.parent / "LEDMatrix" / "config" / "config_secrets.json",
            Path.home() / "LEDMatrix" / "config" / "config_secrets.json",
            Path("../LEDMatrix/config/config_secrets.json"),
        ]
        
        for config_path in possible_paths:
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config = json.load(f)
                    token = config.get('github', {}).get('api_token', '').strip()
                    if token and token != "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN":
                        print(f"✓ Loaded GitHub token from {config_path}")
                        return token
    except Exception as e:
        pass  # Silently continue to try other methods
    
    # Try environment variable as fallback
    import os
    env_token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
    if env_token:
        print("✓ Loaded GitHub token from environment variable")
        return env_token
    
    return None


def main():
    parser = argparse.ArgumentParser(
        description='Update plugins.json with latest versions from GitHub'
    )
    parser.add_argument(
        '--token',
        help='GitHub personal access token (for higher API rate limits). If not provided, will try to load from LEDMatrix config_secrets.json',
        default=None
    )
    parser.add_argument(
        '--registry',
        help='Path to plugins.json file',
        default='plugins.json'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without making changes'
    )
    
    args = parser.parse_args()
    
    # Auto-load token if not provided
    github_token = args.token
    if not github_token:
        github_token = load_github_token_from_config()
        if not github_token:
            print("⚠️  No GitHub token found. API requests limited to 60/hour.")
            print("   Add token to LEDMatrix/config/config_secrets.json or use --token argument")
    else:
        print("✓ Using GitHub token from command line argument")
    
    try:
        update_plugin_versions(args.registry, github_token, args.dry_run)
    except FileNotFoundError:
        print(f"Error: Could not find {args.registry}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"Error: {args.registry} is not valid JSON")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()

