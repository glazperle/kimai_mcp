#!/usr/bin/env python3
"""Main entry point for kimai_mcp package when run as module."""

import asyncio

from .server import main

if __name__ == "__main__":
    asyncio.run(main())