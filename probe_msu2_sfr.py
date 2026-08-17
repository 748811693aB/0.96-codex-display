#!/usr/bin/env python3
"""Read the MSU2 firmware's 256-byte SFR descriptor table."""

from __future__ import annotations

import argparse
import time

from codex_msu2_display import MSU2Mini


def read_u8(display: MSU2Mini, address: int) -> int:
    assert display.serial is not None
    command = bytes((0, 48, 0, address >> 8, address & 0xFF, 0))
    display.serial.write_all(command)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        response = display.serial.read_until_quiet(timeout=0.1, quiet=0.002)
        if len(response) >= 6:
            return response[5]
    raise TimeoutError(f"No SFR response for address {address}")


def write_u8(display: MSU2Mini, address: int, value: int) -> None:
    assert display.serial is not None
    command = bytes((0, 48, 128, address >> 8, address & 0xFF, value & 0xFF))
    display.serial.write_all(command)
    display.serial.read_until_quiet(timeout=0.5, quiet=0.002)


def take_c_string(data: bytes, offset: int) -> tuple[bytes, int]:
    end = data.find(b"\0", offset)
    if end < 0:
        raise ValueError("Unterminated SFR descriptor string")
    return data[offset:end], end + 1


def parse_descriptors(data: bytes) -> list[tuple[str, str, int, bytes]]:
    result: list[tuple[str, str, int, bytes]] = []
    offset = 0
    while offset < len(data) and data[offset] != 0:
        name_raw, offset = take_c_string(data, offset)
        unit_raw, offset = take_c_string(data, offset)
        family_raw, offset = take_c_string(data, offset)
        if not family_raw:
            break
        family = family_raw[0]
        kind = family // 32
        if kind == 0:
            data_length = 2
        elif kind == 1:
            data_length = 1
        elif kind == 2:
            data_length = 2
        elif kind in (3, 4):
            data_length = family % 32
        else:
            break
        value = data[offset : offset + data_length]
        offset += data_length
        result.append(
            (
                name_raw.decode("gbk", errors="replace"),
                unit_raw.decode("gbk", errors="replace"),
                family,
                value,
            )
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--device-glob", default="/dev/cu.usbmodem01234567891")
    parser.add_argument("--base", type=int, default=256)
    parser.add_argument("--read-address", type=lambda value: int(value, 0))
    parser.add_argument("--write-value", type=lambda value: int(value, 0))
    args = parser.parse_args()
    display = MSU2Mini(args.device_glob, lcd_state=0)
    try:
        display.connect()
        if args.read_address is not None:
            before = read_u8(display, args.read_address)
            print(f"SFR[0x{args.read_address:04x}] before = 0x{before:02x}")
            if args.write_value is not None:
                write_u8(display, args.read_address, args.write_value)
                after = read_u8(display, args.read_address)
                print(f"SFR[0x{args.read_address:04x}] after = 0x{after:02x}")
            return 0
        table = bytes(read_u8(display, args.base + address) for address in range(256))
        print(f"SFR raw: {table.hex()}")
        for name, unit, family, value in parse_descriptors(table):
            print(f"{name!r} unit={unit!r} family=0x{family:02x} data={value.hex()}")
    finally:
        display.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
