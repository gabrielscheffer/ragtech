#!/bin/bash
# Instalador para o bridge Ragtech → NUT no Proxmox
# Roda como root.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=========================================="
echo "Instalando Ragtech Easy Pro → NUT bridge"
echo "Repositório: $REPO_DIR"
echo "=========================================="

# 1. Dependências
echo "[1/8] Instalando dependências..."
apt update
apt install -y nut nut-client nut-server python3-serial

# 2. Script Python
echo "[2/8] Instalando script Python..."
install -m 0755 -o root -g root \
    "$REPO_DIR/src/ragtech-nut.py" \
    /usr/local/bin/ragtech-nut.py

# 3. Script de shutdown
echo "[3/8] Instalando script de shutdown gracioso..."
install -m 0755 -o root -g root \
    "$REPO_DIR/scripts/proxmox-graceful-shutdown.sh" \
    /usr/local/bin/proxmox-graceful-shutdown.sh

# 4. Regra udev
echo "[4/8] Instalando regra udev..."
install -m 0644 -o root -g root \
    "$REPO_DIR/udev/62-ragtech-nut.rules" \
    /etc/udev/rules.d/62-ragtech-nut.rules

udevadm control --reload-rules
udevadm trigger

# 5. Permissões — usuário nut em dialout para acesso à serial
echo "[5/8] Adicionando usuário 'nut' ao grupo 'dialout'..."
usermod -aG dialout nut

# 6. Diretório de dados
echo "[6/8] Criando diretório de dados..."
mkdir -p /var/lib/nut
chown nut:nut /var/lib/nut
chmod 770 /var/lib/nut

# 7. Configurações do NUT
echo "[7/8] Instalando configurações do NUT..."
echo "      ⚠️  Configurações existentes serão renomeadas para .bak"

for f in nut.conf ups.conf upsd.conf upsd.users upsmon.conf; do
    if [ -f "/etc/nut/$f" ]; then
        cp "/etc/nut/$f" "/etc/nut/$f.bak.$(date +%s)"
    fi
    install -m 0640 -o root -g nut "$REPO_DIR/nut/$f" "/etc/nut/$f"
done

# 8. Systemd unit
echo "[8/8] Instalando systemd unit..."
install -m 0644 -o root -g root \
    "$REPO_DIR/systemd/ragtech-nut.service" \
    /etc/systemd/system/ragtech-nut.service

systemctl daemon-reload

echo ""
echo "=========================================="
echo "✅ Instalação concluída!"
echo "=========================================="
echo ""
echo "PRÓXIMOS PASSOS (manuais):"
echo ""
echo "1. Edite as senhas em:"
echo "   /etc/nut/upsd.users"
echo "   /etc/nut/upsmon.conf"
echo ""
echo "2. Inicie os serviços:"
echo "   systemctl enable --now ragtech-nut.service"
echo "   systemctl enable --now nut-driver@ragtech.service"
echo "   systemctl enable --now nut-server.service"
echo "   systemctl enable --now nut-monitor.service"
echo ""
echo "3. Teste a integração:"
echo "   upsc ragtech@localhost"
echo ""
echo "4. Logs em tempo real:"
echo "   journalctl -fu ragtech-nut.service"
echo "   journalctl -fu nut-monitor.service"
