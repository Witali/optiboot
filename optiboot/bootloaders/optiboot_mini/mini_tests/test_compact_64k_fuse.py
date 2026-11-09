#!/usr/bin/env python3
"""Compact 64KiB class, EEPROM-first, optional real fuse/lock reads.

Software AVR opcode emulator only; no silicon, real AVRDUDE, or UART timings.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini
from test_modern_audit import AVRModern
from test_all_mcusr_spm_parity import with_mcusr
from test_legacy_uart import symaddr


class TestCompact64KEepromFuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='compact64k-')
        cls.data={}
        for chip in build_mini.COMPACT_64K:
            cls.data[chip]={}
            for option in ('eeprom512','fuse_read'):
                folder=Path(cls.temp.name)/chip/option
                cmd=[sys.executable,str(ROOT/'build_mini.py'), '--mcu',chip,
                     '--compact-644' if chip in build_mini.COMPACT_644 else '--compact-64k',
                     '--f-cpu','16000000','--baud','115200','--output-dir',str(folder)]
                if option=='fuse_read':cmd+=['--fuse-lock-read']
                cp=subprocess.run(cmd,capture_output=True,text=True)
                if cp.returncode:raise RuntimeError(f'{chip}/{option}: {cp.stderr}')
                cls.data[chip][option]=((folder/(chip+'.bin')).read_bytes(),
                                        folder/(chip+'.o'),
                                        json.loads((folder/(chip+'.json')).read_text()))

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def cpu(self,chip,option='eeprom512',mcusr=2):
        image,obj,_=self.data[chip][option]
        dev=build_mini.DEVICES[chip]
        cpu=with_mcusr(AVRModern(image,dev['flash'],dev['page'],dev['eeprom'],mcusr),dev)
        cpu.rxwait_pc=cpu.boot_start+symaddr(obj,'rx_wait')
        cpu.error_pc=cpu.boot_start+symaddr(obj,'error_loop')
        cpu.wait_ready()
        return cpu

    @staticmethod
    def read(c,length,kind='E'):
        return c.send(bytes((0x74,length>>8,length&255,ord(kind),0x20)))

    @staticmethod
    def write(c,data,kind='E'):
        n=len(data)
        return c.send(bytes((0x64,n>>8,n&255,ord(kind)))+data+b' ')

    def test_payload_size_and_hardware_footprint(self):
        self.assertEqual(len(build_mini.COMPACT_64K),5)
        for chip in self.data:
            with self.subTest(chip=chip):
                old=self.data[chip]['eeprom512'][2]
                enhanced=self.data[chip]['fuse_read'][2]
                self.assertEqual((old['code_bytes'],old['footer_bytes']), (492,5))
                self.assertEqual((enhanced['code_bytes'],enhanced['footer_bytes']), (528,5))
                self.assertTrue(old['payload_under_512'])
                self.assertFalse(enhanced['payload_under_512'])
                self.assertEqual(old['compact_payload_bytes'],497)
                self.assertEqual(enhanced['compact_payload_bytes'],533)
                self.assertEqual(old['boot_bytes'],enhanced['boot_bytes'])
                self.assertEqual(old['boot_bytes'],1024)
                self.assertEqual(old['boot_start_hex'],'0xFC00')
                self.assertTrue(enhanced['stk_universal_fuse_lock_reads'])
                self.assertFalse(old['stk_universal_fuse_lock_reads'])
                for opt in ('eeprom512','fuse_read'):
                    image,obj,meta=self.data[chip][opt]
                    self.assertEqual(image[-5:],bytes(build_mini.DEVICES[chip]['sig'])+b'\x03\x08')
                    self.assertEqual(symaddr(obj,'optiboot_mini_do_spm'),2)
                    self.assertEqual(meta['app_spm_entry_byte_address'],0xFC02)

    def test_eeprom_read_write_full_last_address_and_bounds(self):
        for chip in self.data:
            size=build_mini.DEVICES[chip]['eeprom']
            for option in ('eeprom512','fuse_read'):
                with self.subTest(chip=chip,option=option):
                    c=self.cpu(chip,option)
                    for offset in (0,18,size-16):
                        data=bytes((i*11+offset//2)&255 for i in range(16))
                        self.assertEqual(c.load_address(offset),b'\x14\x10')
                        self.assertEqual(self.write(c,data),b'\x14\x10')
                        self.assertEqual(bytes(c.eeprom[offset:offset+16]),data)
                        self.assertEqual(self.read(c,16),b'\x14'+data+b'\x10')
                    self.assertEqual(c.erase_count,0)
                    bad=self.cpu(chip,option)
                    self.assertEqual(bad.load_address(size-2),b'\x14\x10')
                    bad.execute_until_error(b'd\x00\x10E'+bytes(range(16))+b' ',bad.error_pc)
                    self.assertEqual(bad.eeprom,b'\xff'*size)

    def test_eeprom_bad_eop_does_not_write(self):
        for chip in self.data:
            for opt in ('eeprom512','fuse_read'):
                with self.subTest(chip=chip,opt=opt):
                    c=self.cpu(chip,opt)
                    c.load_address(0)
                    c.execute_until_error(b'd\x00\x10E'+bytes(range(16))+b'!',c.error_pc)
                    self.assertEqual(c.eeprom[:16],b'\xff'*16)

    def test_flash_program_and_boot_guard(self):
        for chip in self.data:
            for opt in ('eeprom512','fuse_read'):
                with self.subTest(chip=chip,opt=opt):
                    c=self.cpu(chip,opt)
                    address=0xFB00
                    data=bytes((i*19+27)&255 for i in range(256))
                    c.load_address(address)
                    self.assertEqual(self.write(c,data,'F'),b'\x14\x10')
                    self.assertEqual(c.flash[address:address+256],data)
                    c.load_address(address)
                    self.assertEqual(self.read(c,256,'F'),b'\x14'+data+b'\x10')
                    c.load_address(0xFC00)
                    c.execute_until_error(b'd\x01\x00F'+data+b' ',c.error_pc)
                    self.assertEqual(c.erase_count,1)

    def test_stk_signatures_params_and_fuse_lock(self):
        for chip in self.data:
            for opt in ('eeprom512','fuse_read'):
                with self.subTest(chip=chip,opt=opt):
                    c=self.cpu(chip,opt)
                    self.assertEqual(c.send(b'0 '),b'\x14\x10')
                    self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                    self.assertEqual(c.send(b'A\x82 '),b'\x14\x03\x10')
                    self.assertEqual(c.send(b'u '),b'\x14'+bytes(build_mini.DEVICES[chip]['sig'])+b'\x10')
                    for i,v in enumerate(build_mini.DEVICES[chip]['sig']):
                        self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),bytes((0x14,v,0x10)))
                    for (a,b),v in zip(((0x50,0),(0x58,0),(0x50,8),(0x58,8)),(0x62,0xff,0xff,0xd9)):
                        expected=v if opt=='fuse_read' else 0
                        self.assertEqual(c.send(bytes((0x56,a,b,0,0,0x20))),bytes((0x14,expected,0x10)))
                    self.assertEqual(c.send(b'V\xac\x53\x00\x00 '),b'\x14\x00\x10')
                    self.assertEqual(c.send(b'B'+bytes(20)+b' '),b'\x14\x10')
                    self.assertEqual(c.send(b'E'+bytes(5)+b' '),b'\x14\x10')

    def test_spm_abi_and_reset_behavior(self):
        for chip in self.data:
            for opt in ('eeprom512','fuse_read'):
                with self.subTest(chip=chip,opt=opt):
                    c=self.cpu(chip,opt)
                    original={r:c.reg[r] for r in (*range(2,18),28,29)}
                    address=0xFB00
                    c.reg[24],c.reg[25]=address&255,address>>8
                    c.reg[22]=3
                    c.reg[20]=c.reg[21]=0
                    c.flash[address:address+2]=b'\x00\x00'
                    c.stack.append(0x0400)
                    c.pc=c.boot_start+2
                    for _ in range(1000):
                        if c.pc==0x0400:break
                        c.step()
                    else:self.fail('SPM app API did not return')
                    self.assertEqual(c.flash[address:address+2],b'\xff\xff')
                    for r,v in original.items():self.assertEqual(c.reg[r],v)
                    for reason in (0,1,2,8,10):
                        d=build_mini.DEVICES[chip]
                        im,_,_=self.data[chip][opt]
                        reset=with_mcusr(AVRModern(im,d['flash'],d['page'],d['eeprom'],reason),d)
                        rx=reset.boot_start+symaddr(self.data[chip][opt][1],'rx_wait')
                        for _ in range(300):
                            if reset.pc in (0,rx) or reset.app_started:break
                            reset.step()
                        self.assertEqual(reset.pc==rx,reason==0 or reason&10==2)

    def test_builder_rejects_wrong_fuse_option(self):
        with tempfile.TemporaryDirectory() as td:
            args=[sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p',
                  '--app-spm-512','--fuse-lock-read','--output-dir',td]
            p=subprocess.run(args,capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0)
            self.assertIn('requires',p.stderr)

if __name__=='__main__':unittest.main()
