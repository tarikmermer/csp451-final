#!/bin/bash
set -e
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$PROJECT_ROOT/venv"
echo " Setting up SmartRetail Supplier Sync Python Environment.. "
# Create virtual environment
python3 -m venv "$VENV_DIR"
# Activate virtual environment
source "$VENV_DIR/bin/activate"
# Upgrade pip
pip install --upgrade pip
echo " Virtual environment setup complete!"
