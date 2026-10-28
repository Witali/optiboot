#!/usr/bin/env python3
"""Regression for complete page lengths and E/F-only memory types.

Uses assembled instructions, including cases that modified Flash before the
header hardening. The optional exhaustive pass checks all invalid 16-bit lengths
through the shared parser's Flash-read entry. No physical device is accessed.
"""
import argparse
from pathlib import Path
import os


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path)
    parser.add_argument("--exhaustive", action="store_true")
    args = parser.parse_args()
    if args.firmware:
        os.environ["OPTIBOOT_328P_BINARY"] = str(args.firmware.resolve())

    from test_eeprom import pkt_load, pkt_read, pkt_write
    from test_strict_datasheet import init
    from test_universal import FW

    ack = bytes.fromhex("14 10")
    counts = {"rejected": 0, "valid_reads": 0, "valid_writes": 0, "truncated": 0}

    def drive(sim, packet):
        sim.rx.extend(packet)
        start = len(sim.tx)
        for steps in range(200000):
            if sim.io.get(0x60) == 8 and sim.u16(sim.pc) == 0xCFFF:
                return bytes(sim.tx[start:]), "abort"
            if steps > 10 and not sim.rx and sim.pc in (sim.rxwait_pc, sim.rxwait_pc + 4, sim.rxwait_pc + 6):
                return bytes(sim.tx[start:]), "wait"
            sim.step()
        raise AssertionError("Model failed to reach receive polling or the watchdog error loop")

    def rejected(packet, label):
        sim = init()
        sim.flash[:256] = bytes((i ^ 0xA5) for i in range(256))
        sim.eeprom[:256] = bytes((i ^ 0x5A) for i in range(256))
        assert sim.send(pkt_load(0)) == ack
        before_flash, before_eeprom = bytes(sim.flash), bytes(sim.eeprom)
        response, state = drive(sim, packet)
        assert bytes(sim.flash) == before_flash, (label, "invalid header changed Flash")
        assert bytes(sim.eeprom) == before_eeprom, (label, "invalid header changed EEPROM")
        assert not sim.spm_log and not sim.eewrites and not sim.eereads, (label, "header reached a memory peripheral")
        assert state == "abort" and response == b"", (label, state, response.hex())
        counts["rejected"] += 1

    # Direct reproductions of the two memory-changing audit findings.
    rejected(bytes.fromhex("64 01 02 46 aa bb 20"), "oversized declaration committed a prefix")
    rejected(bytes.fromhex("64 00 02 58 aa bb 20"), "unknown type selected Flash")

    lengths = {0, 257, 258, 511, 512, 0x7FFF, 0x8000, 0xFFFF}
    lengths.update((high << 8) | 2 for high in range(1, 256))
    for high in (0, 1, 2, 0x7F, 0xFF):
        lengths.update((high << 8) | low for low in (0, 1, 2, 15, 16, 127, 128, 255))
    for length in sorted(lengths):
        if 1 <= length <= 256:
            continue
        for command in (0x64, 0x74):
            for memory in (ord("E"), ord("F")):
                # Rejection must work without payload or EOP arriving.
                rejected(bytes((command, length >> 8, length & 255, memory)),
                         f"command={command:02x}, length={length}, memory={memory:02x}")

    # Every undeclared memory-type byte, at both read and write entry points.
    for memory in range(256):
        if memory in (ord("E"), ord("F")):
            continue
        for command in (0x64, 0x74):
            rejected(bytes((command, 0, 2, memory)), f"invalid memory type {memory:02x}")

    # All legal full-length encodings, including 0x0100, for both memories.
    data = bytes(range(256))
    for memory in (b"E", b"F"):
        sim = init()
        sim.flash[:256] = data
        sim.eeprom[:256] = data
        for length in range(1, 257):
            assert sim.send(pkt_load(0)) == ack
            assert sim.send(pkt_read(length, memory)) == b"\x14" + data[:length] + b"\x10", (memory, length)
            counts["valid_reads"] += 1

    # Exercise every declared Flash write size, including the 2-byte minimum.
    for length in range(1, 257):
        if length > 128 or length % 2:
            rejected(bytes((0x64, length >> 8, length & 255, ord("F"))), f"Flash write length {length}")
        else:
            sim = init()
            payload = bytes((i * 37 + length) & 255 for i in range(length))
            assert sim.send(pkt_load(0)) == ack
            assert sim.send(pkt_write(payload, b"F")) == ack
            assert sim.flash[:length] == payload and sim.flash[0x7E00:] == FW
            counts["valid_writes"] += 1
    for length in range(1, 257):
        if length > 16:
            rejected(bytes((0x64, length >> 8, length & 255, ord("E"))), f"EEPROM write length {length}")
        else:
            sim = init()
            payload = bytes(range(length))
            assert sim.send(pkt_load(0)) == ack
            assert sim.send(pkt_write(payload)) == ack
            assert sim.eeprom[:length] == payload
            counts["valid_writes"] += 1

    # A valid but incomplete packet must wait without committing memory.
    for memory in (b"E", b"F"):
        packet = pkt_write(bytes(range(16)), memory)
        for split in range(1, len(packet)):
            sim = init()
            before_flash, before_eeprom = bytes(sim.flash), bytes(sim.eeprom)
            response, state = drive(sim, packet[:split])
            assert response == b"" and state == "wait"
            assert bytes(sim.flash) == before_flash and bytes(sim.eeprom) == before_eeprom
            response, state = drive(sim, packet[split:])
            assert response == ack and state == "wait"
            memory_after = sim.eeprom if memory == b"E" else sim.flash
            assert memory_after[:16] == bytes(range(16)), (memory, split, "fragmented payload changed")
            assert sim.flash[0x7E00:] == FW
            counts["truncated"] += 1

    if args.exhaustive:
        for length in range(65536):
            if 1 <= length <= 256:
                continue
            rejected(bytes((0x74, length >> 8, length & 255, ord("F"))), f"exhaustive length {length}")
        print("PASS: every invalid 16-bit length rejected through the shared parser")
    print("PASS: page header validation", counts)
    print("Software-model result only; physical-hardware validation is pending.")


if __name__ == "__main__":
    main()
