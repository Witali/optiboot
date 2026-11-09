"""Regression: R5 used -5 universal signature offset even with 7-byte signon footer.

R6 shares exactly one per-MCU silicon signature in the firmware and returns
that same data through 0x75 READ_SIGN and 0x56 UNIVERSAL (0x30, 0x00).
Instruction-level software emulation; not a silicon/serial test.
"""
from pathlib import Path
import json, sys, unittest
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini
from test_r5_signon_1024 import R5SignOn, SIGNON

OUT=ROOT/'output'/'compat_r6_signon'

@unittest.skipUnless((OUT/'matrix.json').is_file(), 'Historical comparison requires snapshots omitted from the 2026-11-08 archive')
class R6SignatureRegression(unittest.TestCase):
    def test_signon_and_universal_both_read_correct_signature(self):
        # Every architecture with the new compact sign-on; model covers these classes.
        original=R5SignOn.ROOT_OUT if hasattr(R5SignOn,'ROOT_OUT') else None
        for chip in ('atmega644p','atmega640','atmega64a','atmega128a','atmega1284p','atmega2560',
                     'attiny841','attiny1634','attiny84','attiny85'):
            with self.subTest(chip=chip):
                # Reuse the existing R5 model, overriding its output folder only for this invocation.
                import test_r5_signon_1024 as t
                prior=t.ROOT_OUT
                t.ROOT_OUT=OUT
                try: c=R5SignOn().cpu(chip)
                finally: t.ROOT_OUT=prior
                expected=bytes(build_mini.DEVICES[chip]['sig'])
                def tx(query, expected_length):
                    if chip in ('attiny84','attiny85'):
                        c.send_wave(query)
                        return c.decoded_transmit()[-expected_length:]
                    return c.send(query)
                self.assertEqual(tx(b'1 ',len(SIGNON)),SIGNON)
                self.assertEqual(tx(b'u ',5),b'\x14'+expected+b'\x10')
                for ix,val in enumerate(expected):
                    self.assertEqual(tx(bytes((0x56,0x30,0,ix,0,0x20)),3),bytes((0x14,val,0x10)))
                for ix in (3,4,255):
                    self.assertEqual(tx(bytes((0x56,0x30,0,ix,0,0x20)),3),b'\x14\x00\x10')
                self.assertEqual(tx(b'1 ',len(SIGNON)),SIGNON)
                self.assertEqual(tx(bytes((0x56,0x50,0x08,0,0,0x20)),3),b'\x14\x00\x10')
    def test_512_baseline_binary_unchanged(self):
        for chip in build_mini.SPM512_COMPATIBLE:
            x=(OUT/chip/(chip+'.bin')).read_bytes()
            y=(ROOT/'output'/'compat_r5_baseline'/chip/(chip+'.bin')).read_bytes()
            self.assertEqual(x,y,chip)

if __name__=='__main__': unittest.main()
