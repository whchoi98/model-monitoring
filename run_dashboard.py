#!/usr/bin/env python3
"""Entry point for the Streamlit monitoring dashboard."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    app_path = Path(__file__).parent / "dashboard" / "app.py"
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(app_path),
        "--server.address", "0.0.0.0",
        "--server.port", "8501",
        "--server.headless", "true",
    ]
    subprocess.run(cmd)


if __name__ == "__main__":
    main()
