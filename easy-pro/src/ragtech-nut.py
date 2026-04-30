#!/usr/bin/env python3
"""
Ragtech Easy Pro 1200VA → NUT bridge

Lê o nobreak Ragtech Easy Pro via serial CDC ACM e escreve as métricas
em formato compatível com o driver `dummy-ups` do NUT.

Modelo testado: Easy Pro 1200VA USB-TI BL (código 4162)
Protocolo: proprietário Ragtech via /dev/ttyACM0 a 2560 baud
Calibrações: validadas experimentalmente em 30/04/2026

Bytes mapeados no frame de 31 bytes (header aa21):
    offset  8  → battery.charge   (byte * 0.393)
    offset 12  → input.voltage    (byte * INPUT_FACTOR)
    offset 14  → ups.load         (% aproximado)
    offset 24  → ups.temperature  (°C diretos)
    offset 29  → status flags     (bit 4 = charging, bit 5 = on battery)
    offset 30  → output.voltage   (byte * INPUT_FACTOR)

Referências:
  - https://github.com/lucianor/ragtech (decoder XML oficial)
  - Comunidade HA: post #41 (Concurser) e #44 (header aa01 vs aa21)
"""

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path

import serial

# ---------- Configuração padrão ----------
DEFAULT_PORT = "/dev/ups0"  # symlink criado por udev
DEFAULT_BAUD = 2560
DEFAULT_DATA_FILE = "/var/lib/nut/ragtech.dev"
DEFAULT_INTERVAL = 5  # segundos entre leituras
DEFAULT_TIMEOUT = 5

# Calibração Easy Pro 1200VA @ 220V
# Validado: byte 211 → 225V real (multímetro)
INPUT_FACTOR = 1.0664
INPUT_NOMINAL = 220
# Comando de request do protocolo
REQUEST_COMMAND = bytes.fromhex("AA0400801E9E")

# Flags do byte de status (offset 28)
FLAG_CHARGING = 0x10  # bit 4
FLAG_ON_BATTERY = 0x20  # bit 5

# Estado de bateria
LOW_BATTERY_THRESHOLD = 20
REPLACE_BATTERY_THRESHOLD = 5


def parse_frame(data: bytes) -> dict | None:
    """Decodifica um frame de 31 bytes do Ragtech Easy Pro."""
    if len(data) < 31:
        logging.warning("Frame curto demais: %d bytes", len(data))
        return None

    if data[0] != 0xAA:
        logging.warning("Sync byte inválido: 0x%02x", data[0])
        return None

    if data[1] != 0x21:
        logging.warning(
            "Header inesperado 0xaa%02x — esperado 0xaa21. "
            "Modelo diferente? Veja post #44 do fórum HA.",
            data[1],
        )
        return None

    battery_charge = round(data[8] * 0.393)
    battery_charge = max(0, min(100, battery_charge))

    input_voltage = round(data[12] * INPUT_FACTOR)
    output_voltage = round(data[30] * INPUT_FACTOR)
    temperature = data[24]
    load = data[14]
    flags = data[29]

    on_battery = bool(flags & FLAG_ON_BATTERY)
    charging = bool(flags & FLAG_CHARGING)

    # Status NUT-style
    status_parts = []
    if battery_charge <= REPLACE_BATTERY_THRESHOLD:
        status_parts.append("RB")
    if on_battery:
        if battery_charge < LOW_BATTERY_THRESHOLD:
            status_parts.append("LB")
        status_parts.append("OB")
        status_parts.append("DISCHRG")
    else:
        status_parts.append("OL")
        if charging:
            status_parts.append("CHRG")

    return {
        "battery.charge": battery_charge,
        "battery.charge.low": LOW_BATTERY_THRESHOLD,
        "input.voltage": input_voltage,
        "input.voltage.nominal": INPUT_NOMINAL,
        "output.voltage": output_voltage,
        "ups.temperature": temperature,
        "ups.load": load,
        "ups.status": " ".join(status_parts),
        "ups.mfr": "Ragtech",
        "ups.model": "Easy Pro 1200VA",
        "device.mfr": "Ragtech",
        "device.model": "NEP 1200 USB-TI BL (4162)",
        "driver.name": "ragtech-nut.py",
        "driver.version": "1.0.0",
        "_raw.frame": data.hex(),
        "_raw.flags": f"0x{flags:02x}",
    }


def write_data_file(metrics: dict, path: Path) -> None:
    """Escreve métricas no formato esperado pelo driver dummy-ups do NUT.

    Formato: uma chave: valor por linha. Comentários com '#'.
    Linhas iniciando com '_' (debug) são prefixadas com '#'.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        f.write("# Ragtech Easy Pro 1200VA — gerado automaticamente\n")
        f.write(f"# Atualizado em: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        for k, v in metrics.items():
            if k.startswith("_"):
                f.write(f"# {k}: {v}\n")
            else:
                f.write(f"{k}: {v}\n")
    os.replace(tmp, path)  # atomic


def read_once(ser: serial.Serial) -> bytes:
    """Envia request e lê resposta do nobreak."""
    ser.reset_input_buffer()
    ser.write(REQUEST_COMMAND)
    time.sleep(2)
    return ser.read(64)


def run_daemon(
    port: str, baud: int, data_file: Path, interval: int, timeout: int
) -> None:
    """Loop principal: lê o nobreak periodicamente e atualiza o arquivo."""
    logging.info(
        "Iniciando daemon: port=%s baud=%d data_file=%s interval=%ds",
        port,
        baud,
        data_file,
        interval,
    )

    consecutive_errors = 0
    max_errors_log = 5  # depois disso, log a cada N tentativas

    while True:
        try:
            with serial.Serial(port, baud, timeout=timeout) as ser:
                while True:
                    try:
                        response = read_once(ser)
                        metrics = parse_frame(response)
                        if metrics:
                            write_data_file(metrics, data_file)
                            if consecutive_errors >= max_errors_log:
                                logging.info(
                                    "Comunicação restaurada após %d erros",
                                    consecutive_errors,
                                )
                            consecutive_errors = 0
                            logging.debug(
                                "OK status=%s bat=%d%% Vin=%dV Vout=%dV T=%d°C load=%d%%",
                                metrics["ups.status"],
                                metrics["battery.charge"],
                                metrics["input.voltage"],
                                metrics["output.voltage"],
                                metrics["ups.temperature"],
                                metrics["ups.load"],
                            )
                        else:
                            consecutive_errors += 1
                            if consecutive_errors <= max_errors_log:
                                logging.warning("Frame inválido")
                    except serial.SerialException as e:
                        logging.error("Erro de serial: %s — reconectando", e)
                        break  # sai do inner loop, reabre a porta
                    except Exception as e:
                        consecutive_errors += 1
                        if consecutive_errors <= max_errors_log:
                            logging.exception("Erro ao processar leitura: %s", e)

                    time.sleep(interval)

        except serial.SerialException as e:
            logging.error("Não foi possível abrir %s: %s", port, e)
            time.sleep(interval * 2)  # espera mais em erro de abertura
        except KeyboardInterrupt:
            logging.info("Encerrando por interrupção")
            return


def run_once(port: str, baud: int, data_file: Path, timeout: int) -> int:
    """Modo one-shot — útil para teste manual ou cron."""
    try:
        with serial.Serial(port, baud, timeout=timeout) as ser:
            response = read_once(ser)
            metrics = parse_frame(response)
            if not metrics:
                print("ERRO: frame inválido", file=sys.stderr)
                print(f"Recebido ({len(response)} bytes): {response.hex()}", file=sys.stderr)
                return 1
            write_data_file(metrics, data_file)
            print("✅ Métricas escritas em", data_file)
            for k, v in metrics.items():
                if not k.startswith("_"):
                    print(f"  {k}: {v}")
            return 0
    except Exception as e:
        print(f"❌ Erro: {e}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bridge Ragtech Easy Pro → NUT dummy-ups",
    )
    parser.add_argument("--port", default=DEFAULT_PORT, help=f"porta serial (padrão: {DEFAULT_PORT})")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument(
        "--data-file",
        type=Path,
        default=Path(DEFAULT_DATA_FILE),
        help=f"arquivo de saída (padrão: {DEFAULT_DATA_FILE})",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL,
        help="intervalo entre leituras em modo daemon (padrão: 5s)",
    )
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--once", action="store_true", help="executa uma única leitura e sai")
    parser.add_argument("--debug", action="store_true", help="logs verbosos")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Garante diretório do arquivo de dados
    args.data_file.parent.mkdir(parents=True, exist_ok=True)

    # SIGTERM cleanly
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if args.once:
        return run_once(args.port, args.baud, args.data_file, args.timeout)
    else:
        run_daemon(args.port, args.baud, args.data_file, args.interval, args.timeout)
        return 0


if __name__ == "__main__":
    sys.exit(main())
