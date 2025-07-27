#!/usr/bin/env python3
"""Main entry point for kimai_mcp package when run as module."""

from .server import main
import asyncio

if __name__ == "__main__":
    asyncio.run(main())