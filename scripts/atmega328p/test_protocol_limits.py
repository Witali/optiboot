#!/usr/bin/env python3
"""Checks for remaining unsupported AVR061 operations and valid page framing.
Header rejection is verified separately by test_header_validation.py.
"""
from test_strict_datasheet import init
from test_eeprom import pkt_load

a=init()
assert a.send(b'1 ')==b'\x14\x10', 'GET_SIGN_ON currently gives no 7-byte AVR STK string'
assert a.send(b'R ')==b'\x14\x10', 'STK_CHIP_ERASE currently ACKs but does not erase'
before=bytes(a.flash)
assert a.send(b'V\xAC\x80\x00\x00 ')==b'\x14\x00\x10', 'UNIVERSAL chip-erase not implemented'
assert bytes(a.flash)==before, 'No chip erase permitted from bootloader'
assert a.send(pkt_load(0))==b'\x14\x10'
assert a.send(b't\x01\x00E ')==b'\x14'+b'\xFF'*256+b'\x10', 'Valid full length 0x0100 must read 256 EEPROM bytes'
assert a.send(b't\x00\x02F ')==b'\x14'+bytes(a.flash[:2])+b'\x10', 'Valid Flash memory type must remain supported'
assert a.send(b'@\x80\x01 ')==b'\x14\x10', 'SET_PARAMETER input parsing expected'
print('DOCUMENTED LIMITS: GET_SIGN_ON unsupported, CHIP_ERASE ACK no-op, UNIVERSAL only fuse/lock reads; valid 256-byte reads and SET_PARAMETER consumption preserved')
