#!/usr/bin/env python3
"""Regression tests for the 512-byte opt-in dual-signature profile.

Checks instruction-level protocol/flash/EEPROM, but NOT hardware serial timing.
This compact variant deliberately replies zero to UNIVERSAL fuse/lock requests.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from test_universal_signature_ide2 import SignatureSimulator
from test_legacy_uart import symaddr


class AVRCompact(SignatureSimulator):
    """Simulate EEPROM IO state, unlike the minimal AVR base smoke simulator."""
    def __init__(self,image,mcusr=2):
        super().__init__(image,mcusr)
        self.eeprom=bytearray(b'\xff'*1024)
        self.eempe_armed=False
    def io_write(self,addr,val):
        if addr==0x3f:  # EECR = I/O 0x1F; EEPROM EEAR at 0x41/0x42
            if val&4:self.eempe_armed=True
            offset=self.io.get(0x41,0)|(self.io.get(0x42,0)<<8)
            if val&2:
                if not self.eempe_armed:raise AssertionError('EEPROM write missing EEMPE')
                if offset>=1024:raise AssertionError('EEPROM address overflow')
                self.eeprom[offset]=self.io.get(0x40,0)
                self.eempe_armed=False
            if val&1:
                if offset>=1024:raise AssertionError('EEPROM address overflow')
                self.io[0x40]=self.eeprom[offset]
            self.io[addr]=0
            return
        super().io_write(addr,val)

class TestCompactSignatures512(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.working = tempfile.TemporaryDirectory()
        cls.out = Path(cls.working.name)
        cmd = [sys.executable, str(ROOT/'build_mini.py'),
               '--mcu','atmega328p','--universal-signature','--compact-signature',
               '--boot-bytes','512','--f-cpu','16000000','--baud','115200',
               '--output-dir',str(cls.out)]
        cp = subprocess.run(cmd,capture_output=True,text=True)
        if cp.returncode:raise RuntimeError(cp.stderr)
        cls.binary = (cls.out/'atmega328p.bin').read_bytes()
        cls.manifest = json.loads((cls.out/'atmega328p.json').read_text())
        cls.rxpc = 0x7e00 + symaddr(cls.out/'atmega328p.o','rx_wait')
        cls.errpc = 0x7e00 + symaddr(cls.out/'atmega328p.o','error_loop')

    @classmethod
    def tearDownClass(cls):cls.working.cleanup()

    def cpu(self,mcusr=2):
        c=AVRCompact(self.binary,mcusr)
        c.rxwait_pc=self.rxpc
        for _ in range(500):
            if c.pc==c.rxwait_pc:break
            c.step()
        else:raise AssertionError('Bootloader did not reach RX poll')
        return c

    def test_size_footer_feature_flags(self):
        self.assertEqual(len(self.binary),512)
        self.assertLessEqual(self.manifest['code_bytes'],500)
        self.assertEqual(self.manifest['boot_start_hex'],'0x7E00')
        self.assertEqual(self.binary[-12:],bytes.fromhex('1e950f')+b'AVR STK'+bytes((3,8)))
        self.assertTrue(self.manifest['stk_read_sign_0x75'])
        self.assertTrue(self.manifest['stk_universal_signature_0x30'])
        self.assertFalse(self.manifest['stk_universal_fuse_lock_reads'])

    def test_signature_signon_and_parameters(self):
        c=self.cpu()
        for pkt,ans in [
            (b'0 ',b'\x14\x10'),(b'u ',bytes.fromhex('14 1e 95 0f 10')),
            (b'1 ',b'\x14AVR STK\x10'),
            (b'A\x81 ',b'\x14\x08\x10'),(b'A\x82 ',b'\x14\x03\x10'),
            (b'B'+bytes(20)+b' ',b'\x14\x10'),
            (b'E'+bytes(5)+b' ',b'\x14\x10'),
            (b'P ',b'\x14\x10'),
        ]:
            self.assertEqual(c.send(pkt),ans,pkt)
        for index,val in enumerate((0x1e,0x95,0x0f)):
            self.assertEqual(c.send(bytes((0x56,0x30,0,index,0,0x20))),bytes((0x14,val,0x10)))

    def test_invalid_signature_and_fuse_limit_documented(self):
        c=self.cpu()
        for pkt in ((0x56,0x30,0,3,0,0x20),(0x56,0x30,0,255,0,0x20),
                    (0x56,0x30,1,1,0,0x20),(0x56,0x50,0,0,0,0x20),
                    (0x56,0x58,8,0,0,0x20),(0x56,0xac,0x53,0,0,0x20)):
            self.assertEqual(c.send(bytes(pkt)),bytes((0x14,0,0x10)),bytes(pkt))

    def test_flash_read_write_and_last_app_page(self):
        c=self.cpu()
        for address in (0,0x0180,0x7d80):
            payload=bytes(((i*13+address//128+7)&255) for i in range(128))
            self.assertEqual(c.send(bytes((0x55,(address>>1)&255,(address>>9)&255,0x20))),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x64,0,128,ord('F')))+payload+b' '),b'\x14\x10')
            self.assertEqual(c.flash[address:address+128],payload)
            self.assertEqual(c.send(bytes((0x55,(address>>1)&255,(address>>9)&255,0x20))),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x74,0,128,ord('F'),0x20))),b'\x14'+payload+b'\x10')
        self.assertEqual(c.flash[0x7e00:],self.binary)
        self.assertEqual(c.write_count,3)

    def test_eeprom_read_write_and_flash_preservation(self):
        c=self.cpu()
        for address,n in ((0,1),(16,16),(1008,16)):
            data=bytes(((i*7+address)&255) for i in range(n))
            self.assertEqual(c.send(bytes((0x55,(address>>1)&255,(address>>9)&255,0x20))),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x64,0,n,ord('E')))+data+b' '),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x74,0,n,ord('E'),0x20))),b'\x14'+data+b'\x10')
        self.assertEqual(c.erase_count,0)
        self.assertEqual(c.flash[0x7e00:],self.binary)

    def test_invalid_eop_preserves_flash(self):
        c=self.cpu()
        target=0x0400
        c.flash[target:target+128]=b'\x55'*128
        c.send(bytes((0x55,(target>>1)&255,(target>>9)&255,0x20)))
        c.rx.extend(bytes((0x64,0,128,ord('F')))+bytes(range(128))+b'!')
        for _ in range(12000):
            if c.pc==self.errpc:break
            c.step()
        else:self.fail('Malformed EOP did not reach watchdog error handler')
        self.assertEqual(c.erase_count,0)
        self.assertEqual(c.flash[target:target+128],b'\x55'*128)

    def test_power_on_and_wdt_reset_enter_application(self):
        for mcusr in (1,8):
            cpu=AVRCompact(self.binary,mcusr)
            for _ in range(500):
                if cpu.app_started:break
                cpu.step()
            self.assertTrue(cpu.app_started,mcusr)

    def test_old_default_512_reference_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p',
                 '--verify-baseline','--output-dir',tmp]
            cp=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(cp.returncode,0,cp.stderr)

if __name__ == '__main__':unittest.main()
