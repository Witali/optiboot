#!/usr/bin/env python3
"""ATmega328P 512-byte do_spm ABI and STK500v1 compatibility regression.

Runs compiled opcodes in the AVR instruction simulator; this is NOT a silicon,
watchdog timing, interrupt timing, lock-bit or physical UART test.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT))
from test_compact_signature_512 import AVRCompact
from test_modern_audit import AVRModern
from test_legacy_uart import symaddr

class AppSPM512Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.p=Path(cls.tmp.name)
        cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p',
             '--f-cpu','16000000','--baud','115200','--boot-bytes','512',
             '--app-spm-512','--output-dir',str(cls.p)]
        z=subprocess.run(cmd,capture_output=True,text=True)
        if z.returncode:raise RuntimeError(z.stderr)
        cls.image=(cls.p/'atmega328p.bin').read_bytes()
        cls.meta=json.loads((cls.p/'atmega328p.json').read_text())
        cls.o=cls.p/'atmega328p.o'
        cls.rxpc=0x7e00+symaddr(cls.o,'rx_wait')
        cls.errpc=0x7e00+symaddr(cls.o,'error_loop')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def cpu(self):
        c=AVRCompact(self.image)
        c.rxwait_pc=self.rxpc
        for _ in range(1000):
            if c.pc==self.rxpc:break
            c.step()
        else: self.fail('SPM512 boot did not reach UART receive')
        return c

    def app_cpu(self):
        c=AVRModern(self.image,32768,128,1024)
        c.rxwait_pc=self.rxpc
        c.wait_ready()
        c.spm_count=0
        orig_spm=c.spm
        def trace():
            c.spm_count+=1
            orig_spm()
        c.spm=trace
        return c

    def invoke(self,c,addr,command,data=0):
        before={r:c.reg[r] for r in range(2,18)}
        before.update({r:c.reg[r] for r in (28,29)})
        c.io[0x5f]=0x83
        c.reg[24],c.reg[25]=addr&255,(addr>>8)&255
        c.reg[22]=command
        c.reg[20],c.reg[21]=data&255,(data>>8)&255
        c.pc=c.boot_start+2
        returnpc=0x300
        c.stack.append(returnpc)
        for i in range(5000):
            if c.pc==returnpc:
                self.assertEqual(c.reg[1],0)
                self.assertEqual(c.io[0x5f],0x83)
                self.assertEqual({r:c.reg[r] for r in before},before)
                return i
            c.step()
        self.fail('do_spm() failed to RET')

    def test_image_and_abi_exact(self):
        m=self.meta
        self.assertEqual(len(self.image),512)
        self.assertEqual(m['code_bytes'],498)
        self.assertEqual(m['footer_bytes'],5)
        self.assertEqual(self.image[-5:],bytes.fromhex('1e 95 0f 03 08'))
        self.assertTrue(m['app_spm'])
        self.assertTrue(m['app_spm_512'])
        self.assertEqual(m['boot_start_hex'],'0x7E00')
        self.assertEqual(m['app_spm_entry_byte_address'],0x7E02)
        self.assertEqual(symaddr(self.o,'app_spm_service'),2)
        self.assertEqual(symaddr(self.o,'optiboot_mini_do_spm'),2)
        self.assertEqual(self.image[2:4],bytes.fromhex('9e37'))
        self.assertEqual(int.from_bytes(self.image[:2],'little')&0xf000,0xc000)
        self.assertTrue(m['stk_read_sign_0x75'])
        self.assertTrue(m['stk_universal_signature_0x30'])
        self.assertFalse(m['stk_universal_fuse_lock_reads'])
        self.assertFalse(m['stk_get_sign_on_string'])
        self.assertFalse(m['stk_set_parameter_2byte'])

    def test_stk500v1_core(self):
        c=self.cpu()
        for q,a in ((b'0 ',b'\x14\x10'),
                    (b'u ',bytes.fromhex('14 1e 95 0f 10')),
                    (b'1 ',b'\x14\x10'), # official Optiboot 8.3 doesn't implement string sign-on
                    (b'A\x81 ',b'\x14\x08\x10'),
                    (b'A\x82 ',b'\x14\x03\x10'),
                    (b'B'+bytes(20)+b' ',b'\x14\x10'),
                    (b'E'+bytes(5)+b' ',b'\x14\x10'),
                    (b'P ',b'\x14\x10')):
            self.assertEqual(c.send(q),a,q)
        for i,v in enumerate((0x1e,0x95,0x0f)):
            self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),bytes((0x14,v,0x10)))
        for i in (3,255):
            self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),b'\x14\x00\x10')
        self.assertEqual(c.send(bytes((0x56,0x50,0x08,0,0,0x20))),b'\x14\x00\x10')

    def test_flash_and_eeprom_and_last_page(self):
        c=self.cpu()
        for addr in (0,0x100,0x7d80):
            data=bytes((13*i+addr//128+9)&255 for i in range(128))
            self.assertEqual(c.send(bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20))),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x64,0,128,ord('F')))+data+b' '),b'\x14\x10')
            self.assertEqual(c.flash[addr:addr+128],data)
            c.send(bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20)))
            self.assertEqual(c.send(bytes((0x74,0,128,ord('F'),0x20))),b'\x14'+data+b'\x10')
        for addr in (0,1008):
            ep=bytes((i*9+addr//2)&255 for i in range(16))
            c.send(bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20)))
            self.assertEqual(c.send(bytes((0x64,0,16,ord('E')))+ep+b' '),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x74,0,16,ord('E'),0x20))),b'\x14'+ep+b'\x10')
        self.assertEqual(c.flash[0x7e00:],self.image)

    def test_spm_fill_erase_write_and_automatic_rww(self):
        for addr in (0x200,0x7d80):
            with self.subTest(addr=hex(addr)):
                c=self.app_cpu()
                c.flash[addr:addr+2]=b'\x00\x00'
                self.invoke(c,addr,3,0)
                self.assertEqual(c.flash[addr:addr+2],b'\xff\xff')
                self.invoke(c,addr,1,0x55aa)
                self.assertEqual(c.page_buf[0],0xaa)
                self.assertEqual(c.page_buf[1],0x55)
                self.invoke(c,addr,5,0)
                self.assertEqual(c.flash[addr:addr+2],b'\xaa\x55')
                self.assertGreaterEqual(c.spm_count,5) # erase+RWW, fill, write+RWW
                self.assertEqual(c.flash[c.boot_start:],self.image)

    def test_spm_nonzero_data_skips_auto_rww(self):
        c=self.app_cpu()
        self.invoke(c,0x200,0x03,1)
        self.assertEqual(c.spm_count,1)
        self.invoke(c,0x200,0x11,0)
        self.assertEqual(c.spm_count,2)

    def test_spm_boot_rejected(self):
        c=self.app_cpu()
        before=bytes(c.flash[0x7e00:])
        count=c.spm_count
        for cmd in (1,3,5):
            self.invoke(c,0x7e00,cmd,0)
            self.invoke(c,0x7f80,cmd,0)
        self.assertEqual(c.spm_count,count)
        self.assertEqual(c.flash[0x7e00:],before)

    def test_corrupt_eop_never_erases(self):
        c=self.cpu()
        start=0x400
        c.flash[start:start+128]=b'\x5a'*128
        c.send(bytes((0x55,(start>>1)&255,(start>>9)&255,0x20)))
        c.rx.extend(bytes((0x64,0,128,ord('F')))+bytes(range(128))+b'!')
        for _ in range(14000):
            if c.pc==self.errpc:break
            c.step()
        else:self.fail('Invalid CRC_EOP was not rejected')
        self.assertEqual(c.erase_count,0)
        self.assertEqual(c.flash[start:start+128],b'\x5a'*128)

    def test_invalid_mcu_and_boot_policy_rejected(self):
        for args in (
            ['--mcu','atmega644p','--app-spm-512'],
            ['--mcu','atmega328p','--app-spm-512','--boot-bytes','1024'],
        ):
            z=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),*args],capture_output=True,text=True)
            self.assertNotEqual(z.returncode,0,args)

    def test_inline_asm_uses_correct_call_address(self):
        base=self.p/'callabi'
        (base/'avr').mkdir(parents=True,exist_ok=True)
        (base/'stdint.h').write_text('typedef unsigned short uint16_t; typedef unsigned char uint8_t; typedef unsigned long uint32_t;\n')
        (base/'avr'/'io.h').write_text('#define FLASHEND 32767\n')
        (base/'t.c').write_text('#include "optiboot_mini_app_spm.h"\nvoid test(uint16_t a,uint16_t data) { optiboot_mini_do_spm(a,1,data); }\n')
        o=base/'t.o'
        z=subprocess.run(['clang','-target','avr','-mmcu=atmega328p','-Os','-nostdinc','-I',str(base),'-I',str(ROOT),'-DOPTIBOOT_MINI_BOOT_BYTES=512','-DOPTIBOOT_MINI_SPM512=1','-c',str(base/'t.c'),'-o',str(o)],capture_output=True,text=True)
        self.assertEqual(z.returncode,0,z.stderr)
        b=base/'t.bin'
        subprocess.run(['llvm-objcopy','-O','binary','-j','.text',str(o),str(b)],check=True)
        self.assertIn(bytes.fromhex('0e94013f'),b.read_bytes())

    def test_clock_modes_all_fit(self):
        for clock,baud in ((8000000,38400),(16000000,115200),(20000000,115200)):
            with self.subTest(clock=clock,baud=baud):
                out=self.p/(str(clock))
                z=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p','--f-cpu',str(clock),'--baud',str(baud),'--app-spm-512','--output-dir',str(out)],capture_output=True,text=True)
                self.assertEqual(z.returncode,0,z.stderr)
                x=json.loads((out/'atmega328p.json').read_text())
                self.assertEqual(x['code_bytes'],498)
                self.assertEqual(x['boot_bytes'],512)

if __name__=='__main__':unittest.main()
