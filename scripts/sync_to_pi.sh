#!/bin/bash
# ----------------------------------------------------------------------
# sync_to_pi.sh — Đồng bộ source code bridge project từ laptop sang Pi
#
# Dùng rsync thay vì scp/tar để:
#   - Chỉ copy file thay đổi (nhanh hơn, không tạo file rác)
#   - Tự loại bỏ build/ và file binary (tránh chạy nhầm binary x86 trên ARM64 Pi)
#
# Cách dùng:
#   1. Sửa PI_USER và PI_IP cho đúng môi trường của bạn (dòng dưới)
#   2. chmod +x scripts/sync_to_pi.sh
#   3. ./scripts/sync_to_pi.sh
# ----------------------------------------------------------------------

set -e   # dừng ngay nếu có lỗi, không chạy tiếp lệnh sau

# ── Cấu hình — SỬA THEO MÔI TRƯỜNG THẬT ──
PI_USER="pi"
PI_IP="192.168.1.102"
PI_DEST="~/mqtt-matter-bridge/"

# Đường dẫn local — tự xác định, không cần sửa nếu chạy đúng từ project root
LOCAL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/"

echo "=== Sync $LOCAL_SRC -> $PI_USER@$PI_IP:$PI_DEST ==="

rsync -avz --progress \
  --exclude 'build/' \
  --exclude 'build-pi4/' \
  --exclude '*.o' \
  --exclude '*.a' \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'agent/data/*.db' \
  --exclude 'agent/data/*.db-wal' \
  --exclude 'agent/data/*.db-shm' \
  "$LOCAL_SRC" "${PI_USER}@${PI_IP}:${PI_DEST}"

echo ""
echo "=== Sync xong. Build lại trên Pi: ==="
echo "  ssh ${PI_USER}@${PI_IP}"
echo "  cd ~/mqtt-matter-bridge"
echo "  rm -rf build && cmake -B build && cmake --build build"
