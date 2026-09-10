"""Main entry point for apps.admin.catalog_demo module.

Usage:
  python -m apps.admin.catalog_demo <command> [options]
"""
import sys
from apps.admin.catalog_demo.cli import main

if __name__ == "__main__":
    sys.exit(main())
