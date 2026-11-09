"""R3 cross-architecture byte-saving regressions (instruction-level simulation).

Checks relative PC wrap on banked Flash, direct software UART entries,
legacy AVRDUDE EEPROM byte-addressing, and fuse/lock decoder response.
Not a replacement for physical oscillator/ISP/flash-endurance testing.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT), str(HERE)]
from test_128k import AVR128
from test_expanded_ports import Mega256New
from test_mega64_audit import AVR64
from test_modern_audit import AVRModern
from test_all_mcusr_spm_parity import with_mcusr
from test_legacy_uart import symaddr
import build_mini


class CrossArchitectureR3(unittest.TestCase):
    BANKED = ('atmega1284p','atmega128a','atmega2560')

    @staticmethod
    def load(chip):
        edition='compact' if build_mini.DEVICES[chip].get('dual_compact_enabled',True) else 'full'
        p=ROOT/'output'/'validation_constants'/edition/chip
        return (p/(chip+'.bin')).read_bytes(),p/(chip+'.o'),json.loads((p/(chip+'.json')).read_text())

    def test_banked_rjmp_wraps_to_application_on_power_reset(self):
        for chip in self.BANKED:
            with self.subTest(chip=chip):
                image,obj,meta=self.load(chip)
                c=(Mega256New(image,mcusr=1) if chip=='atmega2560' else
                   AVR128(image,chip=='atmega128a',mcusr=1))
                for _ in range(120):
                    if c.pc==0:break
                    c.step()
                self.assertEqual(c.pc,0)
                self.assertTrue(meta['app_spm'])
                self.assertEqual(symaddr(obj,'optiboot_mini_do_spm'),2)

    def test_soft_uart_entry_routines_have_no_extra_trampoline(self):
        for chip in ('attiny84','attiny85'):
            with self.subTest(chip=chip):
                _,obj,meta=self.load(chip)
                self.assertEqual(symaddr(obj,'rx_wait'),symaddr(obj,'soft_uart_rx'))
                self.assertEqual(symaddr(obj,'tx_wait'),symaddr(obj,'soft_uart_tx'))
                self.assertEqual(meta['compact_payload_bytes'],549)

    def test_old_avrdude_byte_address_mode_still_functions(self):
        chip='atmega128a'
        with tempfile.TemporaryDirectory() as tmp:
            proc=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
                                 '--compact-banked','--legacy-eeprom-byte-address',
                                 '--output-dir',tmp],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            folder=Path(tmp)
            c=AVR128((folder/(chip+'.bin')).read_bytes(),True)
            c.rxwait_pc=c.boot_start+symaddr(folder/(chip+'.o'),'rx_wait')
            c.wait_ready()
            addr=4080  # old client sends a byte address in STK_LOAD_ADDRESS
            self.assertEqual(c.send(bytes((0x55,addr&255,addr>>8,0x20))),b'\x14\x10')
            payload=bytes((i*13+4)&255 for i in range(16))
            self.assertEqual(c.send(b'd\x00\x10E'+payload+b' '),b'\x14\x10')
            self.assertEqual(c.eeprom[addr:addr+16],payload)
            self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+payload+b'\x10')

    def test_fuse_extended_dispatched_parameter_and_universal(self):
        for chip in ('atmega644p','atmega64a'):
            with self.subTest(chip=chip):
                with tempfile.TemporaryDirectory() as tmp:
                    p=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                        '--mcu',chip,'--compact-64k','--fuse-lock-read',
                        '--output-dir',tmp],capture_output=True,text=True)
                    self.assertEqual(p.returncode,0,p.stderr)
                    image=(Path(tmp)/(chip+'.bin')).read_bytes()
                    obj=Path(tmp)/(chip+'.o')
                    if chip=='atmega64a':
                        c=AVR64(image)
                    else:
                        dev=build_mini.DEVICES[chip]
                        c=with_mcusr(AVRModern(image,dev['flash'],dev['page'],dev['eeprom']),dev)
                    c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
                    c.wait_ready()
                    self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                    self.assertEqual(c.send(b'A\x82 '),b'\x14\x03\x10')
                    self.assertEqual(c.send(b'V\x30\x00\x01\x00 '), b'\x14'+bytes([build_mini.DEVICES[chip]['sig'][1]])+b'\x10')
                    for op1,op2,expect in ((0x50,0,0x62),(0x58,0,0xff),(0x50,8,0xff),(0x58,8,0xd9)):
                        self.assertEqual(c.send(bytes((0x56,op1,op2,0,0,0x20))),bytes((0x14,expect,0x10)))
                    self.assertEqual(c.send(b'V\xAC\x53\x00\x00 '),b'\x14\x00\x10')


if __name__=='__main__':unittest.main()
