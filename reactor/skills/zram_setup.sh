#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# REACTOR — ZRAM + Memory Optimization for Oracle ARM 24GB
# ═══════════════════════════════════════════════════════════════════════════════
# Configures:
#   - zram with lz4 compression (60% of RAM)
#   - earlyoom for OOM prevention
#   - vm.overcommit_memory=1
#   - swappiness=100 (prefer zram over disk swap)
#   - tmpfs cache for fast I/O
# ═══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

echo "⚡ REACTOR — ZRAM Setup for Oracle ARM 24GB"
echo "═══════════════════════════════════════════════"

# Must run as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run as root (sudo)"
    exit 1
fi

# ─── Detect RAM ──────────────────────────────────────────────────────────────
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_MB=$((TOTAL_RAM_KB / 1024))
ZRAM_SIZE_MB=$((TOTAL_RAM_MB * 60 / 100))

echo "📊 Total RAM: ${TOTAL_RAM_MB}MB"
echo "📊 ZRAM Size: ${ZRAM_SIZE_MB}MB (60%)"

# ─── Install dependencies ────────────────────────────────────────────────────
echo "📦 Installing dependencies..."
apt-get update -qq
apt-get install -y -qq zram-tools earlyoom > /dev/null 2>&1 || {
    # Fallback for systems without zram-tools
    modprobe zram
}

# ─── Configure ZRAM ──────────────────────────────────────────────────────────
echo "🔧 Configuring ZRAM..."

# Disable existing zram devices
for dev in /dev/zram*; do
    [ -b "$dev" ] && swapoff "$dev" 2>/dev/null || true
done

# Reset zram
if [ -f /sys/class/zram-control/hot_remove ]; then
    for i in $(seq 0 3); do
        echo "$i" > /sys/class/zram-control/hot_remove 2>/dev/null || true
    done
fi

# Load module
modprobe zram num_devices=1 2>/dev/null || true

# Configure zram0
ZRAM_DEV="/dev/zram0"
if [ ! -b "$ZRAM_DEV" ]; then
    cat /sys/class/zram-control/hot_add > /dev/null 2>&1 || true
fi

# Set compression algorithm (lz4 is fastest on ARM)
echo lz4 > /sys/block/zram0/comp_algorithm 2>/dev/null || \
    echo lz4hc > /sys/block/zram0/comp_algorithm 2>/dev/null || \
    echo lzo > /sys/block/zram0/comp_algorithm

# Set size
echo "${ZRAM_SIZE_MB}M" > /sys/block/zram0/disksize

# Format and enable
mkswap "$ZRAM_DEV"
swapon -p 100 "$ZRAM_DEV"

echo "✅ ZRAM enabled: ${ZRAM_SIZE_MB}MB with lz4 compression"

# ─── Kernel Tuning ───────────────────────────────────────────────────────────
echo "🔧 Tuning kernel parameters..."

# Prefer zram swap heavily
sysctl -w vm.swappiness=100

# Allow memory overcommit (needed for GPU model loading)
sysctl -w vm.overcommit_memory=1

# Reduce vfs cache pressure
sysctl -w vm.vfs_cache_pressure=50

# Faster dirty page writeback
sysctl -w vm.dirty_ratio=10
sysctl -w vm.dirty_background_ratio=5

# Persist settings
cat >> /etc/sysctl.d/99-reactor.conf << 'EOF'
vm.swappiness=100
vm.overcommit_memory=1
vm.vfs_cache_pressure=50
vm.dirty_ratio=10
vm.dirty_background_ratio=5
EOF

echo "✅ Kernel parameters configured"

# ─── EarlyOOM ────────────────────────────────────────────────────────────────
echo "🔧 Configuring earlyoom..."

# Configure earlyoom to kill at 5% free RAM / 5% free swap
cat > /etc/default/earlyoom << 'EOF'
EARLYOOM_ARGS="-m 5 -s 5 --avoid '(^|/)(init|systemd|sshd|reactor)$' --prefer '(^|/)(python3?|node)$' -r 60 -n"
EOF

systemctl enable earlyoom 2>/dev/null || true
systemctl restart earlyoom 2>/dev/null || true

echo "✅ EarlyOOM configured (kills at 5% free)"

# ─── tmpfs Cache ─────────────────────────────────────────────────────────────
echo "🔧 Setting up tmpfs cache..."

CACHE_DIR="/tmp/reactor_cache"
mkdir -p "$CACHE_DIR"

# Mount tmpfs (4GB for model caching)
TMPFS_SIZE="4G"
if mountpoint -q "$CACHE_DIR" 2>/dev/null; then
    umount "$CACHE_DIR"
fi
mount -t tmpfs -o size="$TMPFS_SIZE",mode=1777 tmpfs "$CACHE_DIR"

# Add to fstab for persistence
if ! grep -q "reactor_cache" /etc/fstab; then
    echo "tmpfs $CACHE_DIR tmpfs size=$TMPFS_SIZE,mode=1777 0 0" >> /etc/fstab
fi

echo "✅ tmpfs cache: ${TMPFS_SIZE} at ${CACHE_DIR}"

# ─── Disable disk swap if exists ─────────────────────────────────────────────
echo "🔧 Checking disk swap..."
DISK_SWAPS=$(swapon --show=NAME,TYPE --noheadings | grep partition || true)
if [ -n "$DISK_SWAPS" ]; then
    echo "⚠️  Disabling disk swap (zram is faster):"
    echo "$DISK_SWAPS"
    swapoff -a 2>/dev/null || true
    swapon "$ZRAM_DEV" -p 100
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════"
echo "⚡ REACTOR ZRAM Setup Complete"
echo "═══════════════════════════════════════════════"
echo ""
echo "  ZRAM:       ${ZRAM_SIZE_MB}MB (lz4, priority 100)"
echo "  Swappiness: 100"
echo "  Overcommit: always (vm.overcommit_memory=1)"
echo "  EarlyOOM:   active (kill at 5% free)"
echo "  tmpfs:      ${TMPFS_SIZE} at ${CACHE_DIR}"
echo ""
echo "  Memory status:"
free -h
echo ""
echo "  Swap status:"
swapon --show
echo ""
echo "═══════════════════════════════════════════════"
