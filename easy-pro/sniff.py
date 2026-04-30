#!/usr/bin/env python3
import serial
import time

with serial.Serial("/dev/ups0", 2560, timeout=20) as ser:
    ser.write(bytes.fromhex("AA0400801E9E"))
    time.sleep(2)
    response = ser.read(64)
    hex_str = ''.join(f'{byte:02x}' for byte in response)
    print(f"Length: {len(response)} bytes")
    print(f"Hex: {hex_str}")
    
    # Print byte by byte com offset (útil pra mapear)
    for i in range(0, len(hex_str), 2):
        print(f"  offset {i//2:2d} (hex {i:02x}): 0x{hex_str[i:i+2]} = {int(hex_str[i:i+2], 16):3d}")
