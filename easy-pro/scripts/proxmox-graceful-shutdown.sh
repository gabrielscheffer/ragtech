#!/bin/bash
# Shutdown gracioso para Proxmox VE
# Caminho: /usr/local/bin/proxmox-graceful-shutdown.sh
#
# Disparado pelo upsmon quando a bateria está em estado crítico.
# Desliga VMs e LXCs antes do host para evitar corrupção de dados.

set -u

LOGFILE=/var/log/nut-shutdown.log
SHUTDOWN_TIMEOUT=60

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [shutdown] $*" | tee -a "$LOGFILE"
}

log "=========================================="
log "Shutdown disparado pelo NUT (UPS crítico)"
log "=========================================="

# 1. Desligar VMs (KVM)
if command -v qm >/dev/null 2>&1; then
    for vmid in $(qm list 2>/dev/null | awk 'NR>1 && $3=="running" {print $1}'); do
        log "Desligando VM $vmid (timeout ${SHUTDOWN_TIMEOUT}s)"
        qm shutdown "$vmid" --timeout "$SHUTDOWN_TIMEOUT" --forceStop 1 &
    done
fi

# 2. Desligar LXCs
if command -v pct >/dev/null 2>&1; then
    for ctid in $(pct list 2>/dev/null | awk 'NR>1 && $2=="running" {print $1}'); do
        log "Desligando LXC $ctid (timeout ${SHUTDOWN_TIMEOUT}s)"
        pct shutdown "$ctid" --timeout "$SHUTDOWN_TIMEOUT" --forceStop 1 &
    done
fi

# Aguarda todos os shutdowns terminarem (max ~SHUTDOWN_TIMEOUT)
log "Aguardando containers/VMs desligarem..."
wait

# 3. Sincroniza filesystems
log "Sincronizando filesystems"
sync
sync

# 4. Desliga o host
log "Desligando o host"
/sbin/shutdown -h +0 "Bateria do nobreak crítica"
