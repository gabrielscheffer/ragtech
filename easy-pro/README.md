# Ragtech Easy Pro 1200VA → NUT bridge

Integração do nobreak Ragtech Easy Pro 1200VA (modelo `4162` / `NEP 1200 USB-TI BL`) com o **NUT (Network UPS Tools)** em servidores Linux/Proxmox, via engenharia reversa do protocolo proprietário da Ragtech.

> Solução baseada no trabalho prévio de [@gustavocmorais](https://community.home-assistant.io/u/gustavocmorais), [@Concurser](https://community.home-assistant.io/u/Concurser) e [@lucianor](https://github.com/lucianor/ragtech), adaptada e calibrada para o **Easy Pro 1200VA bivolt em rede 220V**.

---

## Por quê?

O Ragtech Easy Pro tem porta USB para monitoramento, mas:

- **Não fala protocolo padrão** (Megatec/Voltronic/HID-PDC) — então NUT/`nutdrv_qx` retorna `Device not supported!`
- O software oficial **Supervise** é Windows-only / Linux com dependências antigas e arquitetura limitada
- A Ragtech **não publica documentação** do protocolo

Esta solução faz a ponte: lê o protocolo proprietário em Python e expõe os dados via driver `dummy-ups` do NUT — assim você ganha shutdown automático, integração com Grafana/Prometheus, notificações, e tudo mais que NUT oferece.

---

## Hardware testado

| Item | Valor |
|---|---|
| Modelo | Ragtech Easy Pro 1200VA USB-TI BL |
| Código Ragtech | 4162 (NEP 1200 USB) |
| USB ID | `04d8:000a` (CDC ACM — Microchip) |
| Baudrate | 2560 |
| Tensão de rede testada | 220V (Criciúma/SC) |
| Host | Dell OptiPlex 5050 SFF — Proxmox VE |

---

## Como funciona

```
                   ┌──────────────────────────────────────────────────┐
                   │           Proxmox Host                           │
                   │                                                  │
   USB ───────────►│  /dev/ups0 (symlink udev → ttyACM0)              │
   (Ragtech)       │       │                                          │
                   │       ▼                                          │
                   │  ┌──────────────────┐                            │
                   │  │ ragtech-nut.py   │                            │
                   │  │ (daemon)         │                            │
                   │  └─────────┬────────┘                            │
                   │            │ escreve a cada 5s                   │
                   │            ▼                                     │
                   │  /var/lib/nut/ragtech.dev                        │
                   │            │                                     │
                   │            │ lê                                  │
                   │            ▼                                     │
                   │  ┌──────────────────┐    ┌─────────────────┐     │
                   │  │ NUT dummy-ups    ├───►│ upsd / upsmon   │     │
                   │  │ driver           │    │                 │     │
                   │  └──────────────────┘    └────────┬────────┘     │
                   │                                   │              │
                   │           ┌───────────────────────┴────────┐     │
                   │           ▼                                ▼     │
                   │  proxmox-graceful-shutdown.sh    upsc/clientes    │
                   │  (em bateria crítica)            (Grafana, etc)  │
                   │                                                  │
                   └──────────────────────────────────────────────────┘
```

---

## Estrutura do repositório

```
.
├── src/
│   └── ragtech-nut.py             # Bridge Python (daemon ou one-shot)
├── nut/
│   ├── nut.conf                   # MODE=standalone
│   ├── ups.conf                   # Driver dummy-ups
│   ├── upsd.conf                  # LISTEN config
│   ├── upsd.users                 # Usuários (TROCAR SENHAS!)
│   └── upsmon.conf                # Monitor + shutdown
├── systemd/
│   └── ragtech-nut.service        # Daemon systemd
├── udev/
│   └── 62-ragtech-nut.rules       # Symlink /dev/ups0 + permissões
├── scripts/
│   ├── install.sh                 # Instalador automatizado
│   └── proxmox-graceful-shutdown.sh # Desliga VMs/LXCs antes do host
└── docs/
    └── protocol.md                # Engenharia reversa do protocolo
```

---

## Instalação rápida

```bash
git clone https://github.com/gabrielscheffer/ragtech.git
cd ragtech/easy-pro
sudo ./scripts/install.sh
```

Depois siga os passos manuais que o instalador imprime no final (definir senhas e habilitar serviços).

---

## Instalação manual passo a passo

### 1. Pré-requisitos

```bash
apt update
apt install -y nut nut-client nut-server python3-serial
```

### 2. Copiar arquivos

```bash
# Script Python
install -m 0755 src/ragtech-nut.py /usr/local/bin/

# Script de shutdown
install -m 0755 scripts/proxmox-graceful-shutdown.sh /usr/local/bin/

# Regra udev (cria /dev/ups0)
install -m 0644 udev/62-ragtech-nut.rules /etc/udev/rules.d/
udevadm control --reload-rules && udevadm trigger

# Configs NUT
install -m 0640 -g nut nut/*.conf nut/*.users /etc/nut/

# Systemd
install -m 0644 systemd/ragtech-nut.service /etc/systemd/system/
systemctl daemon-reload
```

### 3. Permissões

```bash
usermod -aG dialout nut
mkdir -p /var/lib/nut
chown nut:nut /var/lib/nut
chmod 770 /var/lib/nut
```

### 4. Definir senhas

Edite `/etc/nut/upsd.users` e `/etc/nut/upsmon.conf` substituindo `TROCAR_SENHA_UPSMON` pela senha que escolher.

### 5. Iniciar serviços

```bash
systemctl enable --now ragtech-nut.service
systemctl enable --now nut-driver@ragtech.service
systemctl enable --now nut-server.service
systemctl enable --now nut-monitor.service
```

### 6. Validar

```bash
# Métricas brutas do bridge
cat /var/lib/nut/ragtech.dev

# Métricas via NUT
upsc ragtech@localhost
```

Saída esperada:
```
battery.charge: 100
battery.charge.low: 20
device.mfr: Ragtech
device.model: NEP 1200 USB-TI BL (4162)
input.voltage: 224
input.voltage.nominal: 220
output.voltage: 223
ups.load: 9
ups.mfr: Ragtech
ups.model: Easy Pro 1200VA
ups.status: OL
ups.temperature: 25
```

---

## Teste de modo bateria

```bash
# 1. Desligue o nobreak da tomada (mantém equipamentos plugados)
# 2. Aguarde alguns segundos e veja:
upsc ragtech@localhost | grep ups.status
# Esperado: ups.status: OB DISCHRG

# 3. Reconecte a tomada:
upsc ragtech@localhost | grep ups.status
# Esperado: ups.status: OL CHRG
```

---

## Troubleshooting

### `/dev/ups0` não existe
```bash
# Confira o vendor/product ID
lsusb | grep -i microchip
# Esperado: ID 04d8:000a Microchip Technology, Inc.

# Recarregue regras udev
udevadm control --reload-rules
udevadm trigger

# Verifique
ls -la /dev/ups0
```

### Bridge não consegue ler a porta
```bash
# Confira que o usuário nut está no grupo dialout
groups nut

# Verifique se ModemManager está segurando a porta
systemctl status ModemManager
lsof /dev/ttyACM0

# Se necessário, desabilite ModemManager
systemctl disable --now ModemManager
```

### `dummy-ups` não inicia
```bash
# Teste manualmente
/usr/lib/nut/dummy-ups -DDD -a ragtech

# Confira que o arquivo de dados existe
ls -la /var/lib/nut/ragtech.dev

# Confira permissões
chown nut:nut /var/lib/nut/ragtech.dev
```

### Frame inválido / header diferente de `0xaa21`

Modelos diferentes de Ragtech podem usar headers diferentes (visto: `aa01` em alguns NEP 1200s). Edite `src/ragtech-nut.py` na função `parse_frame` para aceitar o seu header.

---

## Calibração

Os valores de calibração foram validados no Easy Pro 1200VA bivolt em rede 220V (medida real: 225V em multímetro). Se o seu setup for diferente:

| Variável | Onde alterar | Como calibrar |
|---|---|---|
| `INPUT_FACTOR` | `src/ragtech-nut.py` | `tensão_real / data[12]` |
| `INPUT_NOMINAL` | `src/ragtech-nut.py` | 115 ou 220 conforme rede |

Use `--once --debug` para ver o frame bruto e ajustar.

---

## Limitações conhecidas

- **`ups.load`** é aproximado e pode estar em VA% em vez de W%. Testes empíricos sugerem precisão de ±5%.
- **Sem suporte a comandos de controle** — bridge é read-only. Não envia shutdown ao nobreak (apenas desliga o host).
- **Apenas 1 frame de protocolo decodificado** — o protocolo Ragtech tem outros comandos não explorados.

---

## Créditos

- [@gustavocmorais](https://community.home-assistant.io/u/gustavocmorais) — sniffing inicial do protocolo + Node-RED flow
- [@Concurser](https://community.home-assistant.io/u/Concurser) — primeira integração com NUT dummy
- [@lucianor](https://github.com/lucianor/ragtech) — extração do `devices.xml` do Supervise
- Discussão original: [Home Assistant Community](https://community.home-assistant.io/t/home-assistant-ragtech-nobreak-easy-pro-ups-monitoring/678828)

---

## Licença

GPL-3.0 (mesma do projeto upstream do Luciano).
