#!/usr/bin/env python3
"""Audit the declared Arduino subset separately from broader AVR061 capabilities.

Runs the assembled firmware in the existing limited AVR model. No serial port or
physical device is accessed. Missing functions are observations, not failures
of the supported profile. See docs/atmega328p/PROTOCOL_REVIEW_2026-10-28.md.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--firmware", type=Path, help="audit a rebuilt 512-byte BIN")
    parser.add_argument("--output", type=Path, help="write the complete JSON observations")
    args = parser.parse_args()
    if args.firmware:
        os.environ["OPTIBOOT_328P_BINARY"] = str(args.firmware.resolve())

    from test_eeprom import pkt_load, pkt_read, pkt_write
    from test_strict_datasheet import init
    from test_universal import FW

    ack = bytes.fromhex("14 10")
    observations = []

    def exchange(sim, packet):
        """Allow incomplete packets; identify the error loop without simulating WDT time."""
        sim.rx.extend(packet)
        start = len(sim.tx)
        for step in range(200000):
            if sim.io.get(0x60) == 8 and sim.u16(sim.pc) == 0xCFFF:
                return bytes(sim.tx[start:]), "watchdog_abort_pending"
            if step > 10 and not sim.rx and sim.pc in (
                sim.rxwait_pc, sim.rxwait_pc + 4, sim.rxwait_pc + 6
            ):
                return bytes(sim.tx[start:]), "uart_wait"
            sim.step()
            if sim.app_started:
                raise AssertionError("Unexpected application entry in a protocol exchange")
        raise AssertionError("Model instruction budget exceeded")

    def profile(name, sim, request, expected, check=None):
        reply, state = exchange(sim, request)
        ok = reply == expected and state == "uart_wait"
        if check is not None:
            ok = ok and bool(check())
        observations.append({"name": name, "category": "supported_profile", "passed": ok})
        assert ok, (name, reply.hex(), expected.hex(), state)

    def observe(name, category, packet, note, setup=None):
        sim = init()
        if setup:
            setup(sim)
        before_flash = bytes(sim.flash)
        before_eeprom = bytes(sim.eeprom)
        reply, state = exchange(sim, packet)
        record = {
            "name": name,
            "category": category,
            "request_hex": packet.hex(" "),
            "response_hex": reply.hex(" "),
            "state": state,
            "application_flash_changed": bytes(sim.flash[:0x7E00]) != before_flash[:0x7E00],
            "eeprom_changed": bytes(sim.eeprom) != before_eeprom,
            "note": note,
        }
        observations.append(record)
        return record

    sim = init()
    # Same field order and extended-parameter count selected by the reviewed host.
    device = bytes.fromhex("86 00 00 01 01 01 01 03 ff ff ff ff 00 80 04 00 00 00 80 00")
    for name, packet, reply in (
        ("get_sync", b"0 ", ack),
        ("software_major", b"A\x81 ", bytes.fromhex("14 08 10")),
        ("software_minor", b"A\x82 ", bytes.fromhex("14 03 10")),
        ("set_device_framing", b"B" + device + b" ", ack),
        ("set_device_ext_count_5", bytes.fromhex("45 05 10 d7 a0 00 20"), ack),
        ("enter_programming", b"P ", ack),
        ("read_atmega328p_signature", b"u ", bytes.fromhex("14 1e 95 0f 10")),
        ("set_parameter_noop_framing", bytes.fromhex("40 83 01 20"), ack),
    ):
        profile(name, sim, packet, reply)

    data = bytes(range(128))  # Includes EOP and command bytes inside the payload.
    profile("flash_load_word_address", sim, pkt_load(0x7D80), ack)
    profile("flash_write_full_last_application_page", sim, pkt_write(data, b"F"), ack,
            lambda: sim.flash[0x7D80:0x7E00] == data and sim.flash[0x7E00:] == FW)
    profile("flash_reload_before_read", sim, pkt_load(0x7D80), ack)
    profile("flash_read_full_last_application_page", sim, pkt_read(128, b"F"), b"\x14" + data + b"\x10")

    eeprom = bytes((i * 37) & 255 for i in range(16))
    profile("eeprom_load_word_address", sim, pkt_load(0x3F0), ack)
    profile("eeprom_write_last_16_bytes", sim, pkt_write(eeprom), ack,
            lambda: sim.eeprom[0x3F0:] == eeprom)
    profile("eeprom_reload_before_read", sim, pkt_load(0x3F0), ack)
    profile("eeprom_read_last_16_bytes", sim, pkt_read(16), b"\x14" + eeprom + b"\x10")
    sim.eeprom[:256] = bytes(range(256))
    profile("eeprom_load_for_256_byte_read", sim, pkt_load(0), ack)
    profile("eeprom_valid_0100_length", sim, bytes.fromhex("74 01 00 45 20"),
            b"\x14" + bytes(range(256)) + b"\x10")
    for op, mid, z in ((0x50, 0, 0), (0x58, 0, 1), (0x50, 8, 2), (0x58, 8, 3)):
        profile(f"fuse_lock_query_{op:02x}_{mid:02x}", sim,
                bytes((0x56, op, mid, 0, 0, 0x20)), bytes((0x14, sim.fuse_values[z], 0x10)))
    profile("concatenated_sync_and_signature", sim, b"0 u ", ack + bytes.fromhex("14 1e 95 0f 10"))

    # Transport fragmentation must not turn payload markers into terminators or
    # cause EEPROM mutation before the final EOP byte arrives.
    packet = pkt_write(bytes(range(16)))
    for split in range(1, len(packet)):
        fragmented = init()
        first, state = exchange(fragmented, packet[:split])
        assert first == b"" and state == "uart_wait" and not fragmented.eewrites
        profile(f"fragmented_eeprom_packet_split_{split}", fragmented, packet[split:], ack,
                lambda: fragmented.eeprom[:16] == bytes(range(16)))
    profile("leave_programming_reply", sim, b"Q ", ack, lambda: sim.io.get(0x60) == 8)

    observe("get_sign_on", "unsupported_capability", b"1 ",
            "No sign-on string; not needed by the reviewed Arduino upload sequence.")
    observe("read_data_single_byte", "unsupported_capability", b"q ",
            "Single-byte EEPROM opcode is absent; use the supported page commands.")
    observe("universal_signature", "unsupported_capability", bytes.fromhex("56 30 00 00 00 20"),
            "UNIVERSAL signature request returns zero; READ_SIGN supplies the signature.")
    observe("chip_erase", "unsupported_capability", b"R ",
            "ACK without erasing; normal Flash programming erases each written page.",
            lambda a: a.flash.__setitem__(slice(0, 128), bytes(128)))
    observe("unknown_parameter", "unsupported_capability", bytes.fromhex("41 7f 20"),
            "Returns 03/OK rather than reporting an unsupported selector.")
    observe("unknown_command", "error_policy_difference", bytes.fromhex("7f 20"),
            "Returns ACK instead of the AVR061 UNKNOWN response.")
    observe("bad_eop", "error_policy_difference", bytes.fromhex("30 00"),
            "Enters the short-WDT error loop instead of replying NOSYNC; model does not time the reset.")
    observe("set_device_ext_count_4", "compatibility_boundary", bytes.fromhex("45 04 10 d7 a0 20"),
            "Waits for more input. Fixed five-byte discard accepts the current host form, not this shorter form; AVR061 page 6 is internally inconsistent.")
    observe("oversize_read_length_0102", "hardening_boundary", bytes.fromhex("74 01 02 45 20"),
            "Declared 258-byte read is outside the <=256-byte protocol range, but is silently processed as two bytes.")
    observe("oversize_write_commits_prefix", "hardening_boundary", bytes.fromhex("64 01 02 46 aa bb 20"),
            "Incomplete/out-of-range 258-byte declaration is treated as a complete two-byte Flash write and changes memory.")
    observe("invalid_memory_type_writes_flash", "hardening_boundary", bytes.fromhex("64 00 02 58 aa bb 20"),
            "Undefined type X takes the Flash path and changes memory. Valid profile packets use only E/F.")

    summary = {
        "firmware_sha256": hashlib.sha256(FW).hexdigest(),
        "model": "limited supplied AVR instruction/peripheral interpreter",
        "avrdude_source_commit": "9aa44d08cb207a80a5d1005ead61142d21fb50de",
        "supported_profile_checks": sum(x["category"] == "supported_profile" for x in observations),
        "supported_profile_failures": sum(x.get("passed") is False for x in observations),
        "observation_counts": dict(Counter(x["category"] for x in observations if x["category"] != "supported_profile")),
        "physical_hardware_tested": False,
        "avrdude_executable_tested": False,
        "observations": observations,
    }
    if args.output:
        args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
