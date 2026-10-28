#!/usr/bin/env python3
"""Executable documentation of intentionally unsupported AVR061 operations.
All these observations show STK500v1 subset compatibility, NOT full compliance.
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
assert a.send(b't\x01\x02E ')==b'\x14'+b'\xFF'*2+b'\x10', 'Read length high byte currently ignored'
assert a.send(b't\x00\x02X ')==b'\x14'+bytes(a.flash[:2])+b'\x10', 'Unknown memtype falls back to Flash'
assert a.send(b'@\x80\x01 ')==b'\x14\x10', 'SET_PARAMETER input parsing expected'
print('DOCUMENTED LIMITS: GET_SIGN_ON unsupported, CHIP_ERASE ACK no-op, UNIVERSAL only fuse/lock reads, READ_PAGE ignores high size byte, unknown memtype treated as Flash; correct SET_PARAMETER consumption')
