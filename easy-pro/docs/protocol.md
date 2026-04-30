# Protocolo Ragtech Easy Pro 1200VA — engenharia reversa

Documentação dos achados experimentais do protocolo proprietário do Ragtech Easy Pro 1200VA (modelo `4162` / NEP 1200 USB-TI BL), via análise de tráfego serial.

---

## Camada física

| Parâmetro | Valor |
|---|---|
| Tipo USB | CDC ACM (porta serial virtual) |
| USB Vendor ID | `0x04d8` (Microchip Technology) |
| USB Product ID | `0x000a` |
| Device | `/dev/ttyACM0` |
| Baudrate | 2560 |
| Data bits | 8 |
| Stop bits | 1 |
| Parity | None |
| Timeout | 100ms |

Outros baudrates aceitos pelo Supervise (não testados aqui): 2400, 2048.

---

## Comando de request

```
AA 04 00 80 1E 9E
```

Resposta: frame de **31 bytes** começando com `aa21` (no Easy Pro 1200VA).

> Modelos diferentes podem retornar com header diferente. Ex: alguns NEP 1200s respondem com `aa01`.

---

## Layout do frame de resposta

Frame capturado no Easy Pro 1200VA em modo OL idle:

```
aa 21 00 0c 00 00 be f3 ff 00 08 c6 d3 03 02 35 f8 00 00 01 82 c2 01 9c 19 00 d3 06 0e 00 d3
```

### Tabela de offsets

| Offset | Hex | Tipo | Significado | Fórmula | Validação |
|---|---|---|---|---|---|
| 0 | `aa` | byte | Sync byte | constante | ✅ |
| 1 | `21` | byte | Family ID? | constante para este modelo | ✅ |
| 2-7 | varia | bytes | Header / metadados | desconhecido | — |
| 8 | `ff` | byte | `battery.charge` (%) | `byte * 0.393` | ✅ 255→100% |
| 9-11 | varia | bytes | Desconhecido | — | — |
| 12 | `d3` | byte | `input.voltage` (V) | `byte * INPUT_FACTOR` | ✅ 211→225V |
| 13 | varia | byte | Desconhecido | — | — |
| 14 | `02` | byte | `ups.load` (%) | `byte` (aprox) | ⚠️ idle=2, com 37W=9 |
| 15 | varia | byte | Desconhecido | — | — |
| 16-23 | varia | bytes | Desconhecido | — | — |
| 24 | `19` | byte | `ups.temperature` (°C) | `byte` direto | ✅ 25→25°C |
| 25-27 | varia | bytes | Desconhecido | — | — |
| 28 | varia | byte | Desconhecido | — | — |
| 29 | `07` | byte | **Status flags** | bitfield | ✅ |
| 29 | varia | byte | Desconhecido | — | — |
| 30 | `d3` | byte | `output.voltage` (V) | `byte * INPUT_FACTOR` | ✅ |

### Calibração

```python
INPUT_FACTOR = 1.0664  # = 225V_real / 211_byte
```

Validado com multímetro: tomada em 225V → byte 12 = `0xd3` (211).
Saída em modo OL ≈ entrada (regulação de ±2%).
Saída em modo OB mantida pela bateria em ~221V.

### Status flags (offset 29)

Bitfield de 8 bits com pelo menos 2 bits identificados:

| Bit | Mask | Significado | Validação |
|---|---|---|---|
| 4 | `0x10` | `CHARGING` (carregando bateria) | ✅ ativo após retorno da rede com bateria <100% |
| 5 | `0x20` | `ON_BATTERY` (modo bateria) | ✅ ativo quando rede ausente |

Valores observados:
| Valor | Estado |
|---|---|
| `0x07` | OL idle, bateria 100% |
| `0x27` | OB (sem rede) |
| `0x34` | OL CHRG (rede voltou, carregando) |

Bits 0, 1, 2 ainda não totalmente decodificados.

---

## Sequência de validação experimental (30/04/2026)

### Teste 1 — OL idle com Bitaxe Gamma (37.4W)

```
Frame: aa21000c0000bef3ff0008c8d2090935f70000018282019c1900d3060e07d1
Output:
  battery.charge: 100
  input.voltage:  224
  output.voltage: 223
  ups.temperature: 25
  ups.load: 9
  ups.status: OL
```

### Teste 2 — OB (cabo retirado da tomada)

```
Frame: aa21000c0000bef3e800f9bb060b0d3a0048000086c000a0160006060e27cf
Output:
  battery.charge: 91
  input.voltage:  6
  output.voltage: 221  (mantida pela bateria!)
  ups.temperature: 22
  ups.load: 13
  ups.status: OB DISCHRG
```

### Teste 3 — OB após 5 minutos (descarga linear)

```
Frame: aa21000c0000bef3d800f8ba060b0d4100480000c2c001a0160006060e27d0
Output:
  battery.charge: 85  (-6% em 5 min)
  input.voltage:  6
  output.voltage: 222
  ups.temperature: 22
  ups.load: 13
  ups.status: OB DISCHRG
```

### Teste 4 — OL CHRG (rede retornou com bateria <100%)

```
Frame: aa21000c0000bef3d500f6c2d40909420000000182e201a11900d5060e34d1
Output:
  battery.charge: 84
  input.voltage:  226
  output.voltage: 223
  ups.temperature: 25
  ups.load: 9
  ups.status: OL CHRG
```

---

## Estimativa de autonomia (Easy Pro 1200VA, bateria interna 12V/7Ah)

Com **37.4W de carga**: descarga de ~1.2% por minuto → **~83 minutos** de autonomia total.

Cargas maiores reduzem proporcionalmente. Estimativa para outras cargas (extrapolação linear, não testada acima de 50W):

| Carga | Autonomia estimada |
|---|---|
| 25W (OptiPlex idle + roteador) | ~120 min |
| 50W (OptiPlex em uso + roteador) | ~60 min |
| 100W | ~30 min |
| 200W | ~15 min |
| 500W (carga máxima nominal) | ~5 min |

---

## Bytes/comandos não decodificados

Há referências em outros forks a comandos adicionais:

```
A0 04 FF E0 08 8B   # "primeiro" — retorna frame com magic 12345678
FF FE 00 8E 01 8F   # "segundo" — retorna apenas 0xC2 (ACK?)
AA 04 00 F3 01 F4   # idem
```

Estes não foram explorados aqui pois `AA 04 00 80 1E 9E` já retorna todos os dados que precisamos para shutdown automático.

---

## Referências

- [`devices.xml`](https://github.com/lucianor/ragtech/blob/main/devices.xml) — XML extraído do Supervise oficial, contém famílias e fórmulas de calibração para vários modelos Ragtech.
- [Tópico HA Community](https://community.home-assistant.io/t/home-assistant-ragtech-nobreak-easy-pro-ups-monitoring/678828) — discussão original.
- [Repo do Luciano](https://github.com/lucianor/ragtech) — base do parsing em Python.
