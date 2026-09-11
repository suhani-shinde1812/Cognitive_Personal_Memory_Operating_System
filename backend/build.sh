#!/usr/bin/env bash
set -e

echo "==> Step 1: Installing CPU-only PyTorch and Torchvision..."
pip install --no-cache-dir torch==2.3.0 torchvision==0.18.0 --index-url https://download.pytorch.org/whl/cpu

echo "==> Step 2: Installing application requirements..."
pip install --no-cache-dir -r requirements.txt

echo "==> Backend build completed successfully!"
