#!/usr/bin/env bash
set -e

echo "==> Step 1: Installing CPU-only PyTorch and Torchvision directly from PyTorch CPU wheels..."
pip install --no-cache-dir \
  https://download.pytorch.org/whl/cpu/torch-2.3.0%2Bcpu-cp310-cp310-linux_x86_64.whl \
  https://download.pytorch.org/whl/cpu/torchvision-0.18.0%2Bcpu-cp310-cp310-linux_x86_64.whl

echo "==> Step 2: Installing application requirements..."
pip install --no-cache-dir -r requirements.txt

echo "==> Backend build completed successfully!"
