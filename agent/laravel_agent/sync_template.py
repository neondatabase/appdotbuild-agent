#!/usr/bin/env python3
"""
Simple Laravel template sync script
Syncs from app-build-template-laravel to laravel_agent/template
"""

import os
import shutil
import argparse
from pathlib import Path
from datetime import datetime

# Paths
SOURCE_DIR = Path("/Users/evgenii.kniazev/projects/app-build-template-laravel")
SCRIPT_DIR = Path(__file__).parent
DEST_DIR = SCRIPT_DIR / "template"

# Essential excludes only
EXCLUDES = {
    '.git',
    '.github',
    'node_modules',
    'vendor',
    '.env',
    '.env.local',
    '*.log',
    '.DS_Store',
    '.idea',
    '.vscode',
}

def should_exclude(path: Path) -> bool:
    """Check if path should be excluded"""
    name = path.name
    
    # Check exact matches and wildcards
    for pattern in EXCLUDES:
        if pattern.startswith('*') and name.endswith(pattern[1:]):
            return True
        if name == pattern:
            return True
    
    # Check if any parent is excluded
    for parent in path.parents:
        if parent.name in EXCLUDES:
            return True
            
    return False

def sync_directories(source: Path, dest: Path, dry_run: bool = False):
    """Sync source to destination"""
    if not source.exists():
        print(f"❌ Source directory not found: {source}")
        return False
        
    if not dest.exists():
        print(f"❌ Destination directory not found: {dest}")
        return False
    
    # Create backup
    if not dry_run:
        backup_dir = dest.parent / f"{dest.name}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"📦 Creating backup: {backup_dir.name}")
        shutil.copytree(dest, backup_dir)
    
    # Build rsync command
    exclude_args = []
    for pattern in EXCLUDES:
        exclude_args.extend(['--exclude', pattern])
    
    cmd = ['rsync', '-av', '--delete'] + exclude_args
    if dry_run:
        cmd.append('--dry-run')
    
    cmd.extend([f"{source}/", f"{dest}/"])
    
    # Execute
    print("🔄 Syncing template...")
    if dry_run:
        print("   (DRY RUN - no changes will be made)")
    
    result = os.system(' '.join(cmd))
    
    if result == 0:
        print("✅ Sync completed successfully!")
        if not dry_run and (dest / '.git').exists():
            shutil.rmtree(dest / '.git')
            print("🧹 Removed .git directory from destination")
        return True
    else:
        print("❌ Sync failed!")
        return False

def main():
    parser = argparse.ArgumentParser(description='Sync Laravel template')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying')
    parser.add_argument('--source', help='Override source directory')
    args = parser.parse_args()
    
    source = Path(args.source) if args.source else SOURCE_DIR
    
    print("Laravel Template Sync")
    print("=" * 40)
    print(f"Source: {source}")
    print(f"Destination: {DEST_DIR}")
    print()
    
    if args.dry_run:
        print("🔍 Running in DRY RUN mode")
        print()
    
    success = sync_directories(source, DEST_DIR, args.dry_run)
    
    if success and args.dry_run:
        print("\n👆 Review changes above. Run without --dry-run to apply.")

if __name__ == "__main__":
    main()