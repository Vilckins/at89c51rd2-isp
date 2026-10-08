#!/usr/bin/env python3
"""
AT89C51RD2 ISP flasher via UART.
Протокол: Intel HEX, эхо + данные + '.' + CRLF.
"""
import argparse
import sys
import time

import serial


DEFAULT_PORT = '/dev/ttyUSB0'
DEFAULT_BAUD = 115200
PAGE_SIZE = 128


# ─────────────────────────── низкий уровень ───────────────────────────

def hex_record(addr, rectype, data):
    """Intel HEX запись (без CRLF)."""
    payload = [len(data), (addr >> 8) & 0xFF, addr & 0xFF, rectype] + list(data)
    payload.append((-sum(payload)) & 0xFF)
    return ':' + ''.join(f'{b:02X}' for b in payload)


def read_until(ser, marker, timeout):
    """Читать из порта, пока не найдём marker или не истечёт timeout."""
    buf = b''
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            if marker in buf:
                break
        else:
            time.sleep(0.005)
    return buf


def send_cmd(ser, cmd, timeout=2.0, quiet=False):
    """Отправить команду, дождаться ответа до '.'."""
    ser.reset_input_buffer()
    ser.write((cmd + '\r\n').encode('ascii'))
    raw = read_until(ser, b'.', timeout)
    if not quiet:
        text = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in raw)
        print(f">> {cmd}")
        print(f"<< {text}")
    return raw


def sync(ser, retries=3):
    """Вход в ISP: отправить 'U', дождаться эха."""
    for attempt in range(1, retries + 1):
        ser.reset_input_buffer()
        ser.write(b'U')
        time.sleep(0.2)
        raw = ser.read(ser.in_waiting or 1)
        if b'U' in raw:
            print(f"[OK] Sync (attempt {attempt})")
            return True
        print(f"[WARN] Sync attempt {attempt}/{retries} failed: {raw!r}")
        time.sleep(0.3)
    return False


# ─────────────────────────── парсинг HEX-файла ───────────────────────────

def read_hex_file(path):
    """Intel HEX → {адрес: байт}."""
    mem = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or not line.startswith(':'):
                continue
            try:
                raw = bytes.fromhex(line[1:])
            except ValueError:
                print(f"[WARN] Bad line {lineno}: {line}")
                continue
            length = raw[0]
            addr = (raw[1] << 8) | raw[2]
            rectype = raw[3]
            data = raw[4:4 + length]
            if rectype == 0x00:
                for i, b in enumerate(data):
                    mem[addr + i] = b
    return mem


def parse_response_data(raw, request, expected_len=None):
    """Отделить эхо от данных в ответе."""
    text = raw.decode('ascii', errors='replace').replace('\r', '').replace('\n', '')
    idx = text.find(request)
    if idx >= 0:
        text = text[idx + len(request):]
    dot = text.find('.')
    if dot >= 0:
        text = text[:dot]
    hexchars = ''.join(c for c in text if c in '0123456789ABCDEFabcdef')
    if len(hexchars) % 2 != 0:
        return None
    try:
        data = bytes.fromhex(hexchars)
    except ValueError:
        return None
    if expected_len and len(data) > expected_len:
        data = data[-expected_len:]
    return data


# ─────────────────────────── операции ───────────────────────────

def read_signature(ser):
    print("[INFO] Signature:")
    for param, name in [(0x00, 'Manufacturer'), (0x01, 'Device ID #1'),
                        (0x02, 'Device ID #2'), (0x03, 'Device ID #3')]:
        rec = hex_record(0x0000, 0x05, [0x00, param])   # ← [0x00, param]
        raw = send_cmd(ser, rec, quiet=True)
        data = parse_response_data(raw, rec)
        value = data.hex().upper() if data else '??'
        print(f"  {name}: {value}")


def read_config(ser):
    print("[INFO] Config:")
    for param, subparam, name in [(0x07, 0x00, 'Security'),
                                  (0x07, 0x01, 'BSB'),
                                  (0x07, 0x02, 'SBV'),
                                  (0x0B, 0x00, 'HW byte')]:
        rec = hex_record(0x0000, 0x05, [param, subparam])
        raw = send_cmd(ser, rec, quiet=True)
        data = parse_response_data(raw, rec)
        value = data.hex().upper() if data else '??'
        print(f"  {name}: {value}")

def full_chip_erase(ser, wait=8.0):
    print("[INFO] Full chip erase...")
    rec = hex_record(0x0000, 0x03, [0x07])
    send_cmd(ser, rec, timeout=wait)
    print("[OK] Erase done")


def flash_firmware(ser, hex_path):
    mem = read_hex_file(hex_path)
    if not mem:
        print("[FAIL] Empty HEX file")
        return False

    addrs = sorted(mem.keys())
    start, end = addrs[0], addrs[-1]
    start_page = (start // PAGE_SIZE) * PAGE_SIZE
    end_page = ((end // PAGE_SIZE) + 1) * PAGE_SIZE
    total = (end_page - start_page) // PAGE_SIZE
    print(f"[INFO] Flash {start:04X}..{end:04X} ({len(mem)} bytes, {total} pages)")

    written = 0
    for page in range(start_page, end_page, PAGE_SIZE):
        page_data = bytes(mem.get(page + i, 0xFF) for i in range(PAGE_SIZE))
        rec = hex_record(page, 0x00, page_data)
        echo = send_cmd(ser, rec, quiet=True)
        written += 1
        pct = written * 100 // total
        sys.stdout.write(f"\r[{pct:3d}%] {written}/{total} page {page:04X}")
        sys.stdout.flush()
        if rec.encode('ascii') not in echo:
            print(f"\n[WARN] No echo for page {page:04X}, retry...")
            echo = send_cmd(ser, rec, quiet=True)
            if rec.encode('ascii') not in echo:
                print(f"\n[FAIL] Page {page:04X} not written")
                return False
    print()
    print("[OK] Firmware flashed")
    return True


def verify_firmware(ser, hex_path):
    """Прочитать чип обратно и сравнить с исходником."""
    mem = read_hex_file(hex_path)
    if not mem:
        return False

    addrs = sorted(mem.keys())
    start, end = addrs[0], addrs[-1]
    start_page = (start // PAGE_SIZE) * PAGE_SIZE
    end_page = ((end // PAGE_SIZE) + 1) * PAGE_SIZE
    total = (end_page - start_page) // PAGE_SIZE
    print(f"[INFO] Verify {total} pages")

    errors = 0
    for idx, page in enumerate(range(start_page, end_page, PAGE_SIZE), 1):
        expected = bytes(mem.get(page + i, 0xFF) for i in range(PAGE_SIZE))
        rec = hex_record(0x0000, 0x04, [
            (page >> 8) & 0xFF, page & 0xFF,
            ((page + PAGE_SIZE - 1) >> 8) & 0xFF, (page + PAGE_SIZE - 1) & 0xFF,
            0x00
        ])
        raw = send_cmd(ser, rec, timeout=3.0, quiet=True)
        actual = parse_response_data(raw, rec, expected_len=PAGE_SIZE)

        pct = idx * 100 // total
        sys.stdout.write(f"\r[{pct:3d}%] {idx}/{total} page {page:04X}")
        sys.stdout.flush()

        if actual is None or len(actual) < PAGE_SIZE:
            print(f"\n[FAIL] Page {page:04X}: short/no data")
            errors += 1
            continue
        if actual != expected:
            for i in range(PAGE_SIZE):
                if actual[i] != expected[i]:
                    print(f"\n[FAIL] Page {page:04X} offset {i:02X}: "
                          f"expected {expected[i]:02X}, got {actual[i]:02X}")
                    break
            errors += 1
    print()
    if errors:
        print(f"[FAIL] {errors} pages with errors")
        return False
    print("[OK] Verification passed")
    return True


def set_bljb(ser, bootloader_at_start):
    """
    BLJB:
      bootloader_at_start=True  → BLJB=0 (загрузчик при старте)
      bootloader_at_start=False → BLJB=1 (приложение при старте)
    """
    value = 0x00 if bootloader_at_start else 0x01
    rec = hex_record(0x0000, 0x03, [0x0A, 0x04, value])
    echo = send_cmd(ser, rec)
    if rec.encode('ascii') not in echo:
        print("[FAIL] BLJB not set")
        return False
    label = 'bootloader' if bootloader_at_start else 'user code'
    print(f"[OK] BLJB = {value:02X} ({label} at startup)")
    # Читаем HSB для контроля
    send_cmd(ser, hex_record(0x0000, 0x05, [0x0B, 0x00]))
    return True


def set_security_level2(ser):
    """Security Level 2. Через ISP не сбрасывается!"""
    rec = hex_record(0x0000, 0x03, [0x05, 0x01])
    echo = send_cmd(ser, rec)
    if rec.encode('ascii') not in echo:
        print("[FAIL] Security Level 2 not set")
        return False
    print("[OK] Security Level 2 set")
    return True


# ─────────────────────────── CLI ───────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description='AT89C51RD2 ISP flasher')
    p.add_argument('hexfile', nargs='?', help='Intel HEX file to flash')
    p.add_argument('-p', '--port', default=DEFAULT_PORT)
    p.add_argument('-b', '--baud', type=int, default=DEFAULT_BAUD)
    p.add_argument('--no-erase', action='store_true', help="Don't erase first")
    p.add_argument('--no-sync', action='store_true', help="Skip sync")
    p.add_argument('--verify', action='store_true', help='Verify after flash')
    p.add_argument('--bootloader-at-start', action='store_true',
                   help='BLJB=0: bootloader at startup')
    p.add_argument('--security2', action='store_true',
                   help='Set Security Level 2 (IRREVERSIBLE!)')
    return p.parse_args()


def confirm(prompt):
    return input(f"{prompt} [yes/NO]: ").strip().lower() == 'yes'


def main():
    args = parse_args()

    try:
        ser = serial.Serial(
            port=args.port, baudrate=args.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=0,
        )
        print(f"[OK] Port {args.port} @ {args.baud}")
    except serial.SerialException as e:
        print(f"[FAIL] Open: {e}")
        sys.exit(1)

    try:
        if not args.no_sync and not sync(ser):
            print("[FAIL] Cannot enter ISP. Check P2.6/P2.7, EA, PSEN.")
            sys.exit(1)

        read_signature(ser)
        read_config(ser)

        if not args.hexfile:
            return

        if not args.no_erase:
            full_chip_erase(ser)
            read_config(ser)

        if not flash_firmware(ser, args.hexfile):
            sys.exit(1)

        if args.verify and not verify_firmware(ser, args.hexfile):
            sys.exit(1)

        choice = input(
            "Startup program?\n"
            "  1 — user code (BLJB=1) [default]\n"
            "  2 — bootloader (BLJB=0)\n"
            "Choice [1]: "
        ).strip() or "1"
        set_bljb(ser, bootloader_at_start=(choice == "2"))

        if args.security2 or confirm(
            "Set Security Level 2? This will BLOCK further ISP access!"
        ):
            set_security_level2(ser)

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted")
    except Exception as e:
        print(f"[FAIL] {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ser.is_open:
            ser.close()
            print("[INFO] Port closed")


if __name__ == '__main__':
    main()