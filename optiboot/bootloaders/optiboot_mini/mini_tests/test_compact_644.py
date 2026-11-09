#!/usr/bin/env python3
"""ATmega644-family 503-byte payload in 1024-byte *hardware* boot section.

Instruction-level behavioral simulation, not physical device testing.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini
from test_modern_audit import AVRModern
from test_legacy_uart import symaddr
from test_all_mcusr_spm_parity import with_mcusr

CHIPS=build_mini.COMPACT_644
OUT=ROOT/'output'/'compact644_tests'

class Compact644Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images={}
        for chip in CHIPS:
            folder=OUT/chip
            subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
                '--compact-644','--output-dir',str(folder)],check=True,capture_output=True,text=True)
            dev=build_mini.DEVICES[chip]
            image=(folder/(chip+'.bin')).read_bytes()
            obj=folder/(chip+'.o')
            meta=json.loads((folder/(chip+'.json')).read_text())
            cls.images[chip]=(dev,image,obj,meta)

    def cpu(self,chip,cause=2):
        dev,image,obj,_=self.images[chip]
        c=with_mcusr(AVRModern(image,dev['flash'],dev['page'],dev['eeprom'],cause),dev)
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        c.error_pc=c.boot_start+symaddr(obj,'error_loop')
        c.wait_ready()
        return c

    @staticmethod
    def load(c,byteaddr):
        return c.send(bytes((0x55,(byteaddr>>1)&255,(byteaddr>>9)&255,0x20)))
    @staticmethod
    def write(c,data,mem='F'):
        n=len(data)
        return c.send(bytes((0x64,n>>8,n&255,ord(mem)))+data+b' ')
    @staticmethod
    def read(c,n,mem='F'):
        return c.send(bytes((0x74,n>>8,n&255,ord(mem),0x20)))
    def should_error(self,c,request):
        c.execute_until_error(request,c.error_pc,limit=160000)

    def test_profiles_layout_and_physical_boot(self):
        self.assertEqual(len(CHIPS),4)
        for chip,(dev,image,obj,m) in self.images.items():
            with self.subTest(chip=chip):
                self.assertEqual(dev['page'],256)
                self.assertEqual(dev['flash'],65536)
                self.assertEqual(len(image),1024)
                self.assertEqual(m['boot_bytes'],1024)
                self.assertEqual(m['code_bytes'],492)
                self.assertEqual(m['footer_bytes'],5)
                self.assertEqual(m['compact_payload_bytes'],497)
                self.assertEqual(m['bootsz1_0_bits'],'11')
                self.assertEqual(m['boot_start_hex'],'0xFC00')
                self.assertTrue(m['compact_644'])
                self.assertTrue(m['app_spm'])
                self.assertFalse(m['app_spm_512'])
                self.assertEqual(m['app_spm_entry_byte_address'],0xFC02)
                self.assertEqual(symaddr(obj,'optiboot_mini_do_spm'),2)
                self.assertEqual(image[-5:],bytes(dev['sig'])+b'\x03\x08')
                self.assertEqual(image[494:1019],b'\xff'*525)

    def test_sync_signatures_parameters_uart(self):
        for chip,(dev,image,_,m) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.assertEqual(c.io[0xc1],0x18)
                self.assertEqual(c.io[0xc2],6)
                self.assertEqual(c.io[0xc4],m['ubrr'])
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'P '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                for i,v in enumerate(dev['sig']):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),bytes((0x14,v,0x10)))
                self.assertEqual(c.send(b'V\x30\x00\x03\x00 '),b'\x14\x00\x10')
                self.assertEqual(c.send(b'V\x50\x00\x00\x00 '),b'\x14\x00\x10') # compact fuse reads unavailable
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                self.assertEqual(c.send(b'A\x82 '),b'\x14\x03\x10')
                self.assertEqual(c.send(b'B'+bytes(20)+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'E'+bytes(5)+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'1 '),b'\x14\x10')

    def test_full_256_byte_page_at_first_and_last_address(self):
        for chip,(dev,image,obj,m) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                for address in (0,0x0200,0xFB00):
                    data=bytes((i*13+(address>>8)*17)&255 for i in range(256))
                    self.assertEqual(self.load(c,address),b'\x14\x10')
                    self.assertEqual(self.write(c,data),b'\x14\x10')
                    self.assertEqual(c.flash[address:address+256],data)
                    self.assertEqual(self.load(c,address),b'\x14\x10')
                    self.assertEqual(self.read(c,256),b'\x14'+data+b'\x10')
                self.assertEqual(bytes(c.flash[c.boot_start:]),image)
                self.assertEqual(c.erase_count,3)
                self.assertEqual(c.write_count,3)
                # Historical STK500 zero length can stand for a full 256-byte page.
                data=bytes((255-i)&255 for i in range(256))
                self.load(c,0x1000)
                self.assertEqual(c.send(b'd\x00\x00F'+data+b' '),b'\x14\x10')
                self.assertEqual(c.flash[0x1000:0x1100],data)

    def test_partial_flash_pages_and_256_byte_read(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                for i,n in enumerate((2,4,128,254)):
                    addr=0x1200+i*256
                    data=bytes((x*37+n)&255 for x in range(n))
                    self.assertEqual(self.load(c,addr),b'\x14\x10')
                    self.assertEqual(self.write(c,data),b'\x14\x10')
                    self.assertEqual(c.flash[addr:addr+n],data)
                    self.assertEqual(self.load(c,addr),b'\x14\x10')
                    self.assertEqual(self.read(c,n),b'\x14'+data+b'\x10')
                page=0x2000
                c.flash[page:page+256]=bytes(range(256))
                self.load(c,page)
                self.assertEqual(self.read(c,256),b'\x14'+bytes(range(256))+b'\x10')

    def test_eeprom_first_last_and_memory_type(self):
        for chip,(dev,_,_,_) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                for address in (0,64,dev['eeprom']-16):
                    val=bytes((i*11+(address>>4))&255 for i in range(16))
                    self.assertEqual(self.load(c,address),b'\x14\x10')
                    self.assertEqual(self.write(c,val,'E'),b'\x14\x10')
                    self.assertEqual(bytes(c.eeprom[address:address+16]),val)
                    self.assertEqual(self.load(c,address),b'\x14\x10')
                    self.assertEqual(self.read(c,16,'E'),b'\x14'+val+b'\x10')
                self.assertEqual(c.erase_count,0)

    def test_corrupt_crc_and_boot_write_never_erase(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.load(c,0xFB00)
                self.should_error(c,b'd\x01\x00F'+bytes(range(256))+b'!')
                self.assertEqual(c.erase_count,0)
                c=self.cpu(chip)
                self.load(c,0xFC00)
                self.should_error(c,b'd\x01\x00F'+bytes(range(256))+b' ')
                self.assertEqual(c.erase_count,0)

    def test_invalid_flash_lengths_and_alignment(self):
        for chip in CHIPS:
            for high,low,payload in ((1,1,b'\x00'),(2,0,b''),(0,3,b'\x00'*3)):
                with self.subTest(chip=chip,high=high,low=low):
                    c=self.cpu(chip)
                    self.load(c,0x0200)
                    self.should_error(c,bytes((0x64,high,low,ord('F')))+payload+b' ')
                    self.assertEqual(c.erase_count,0)
            with self.subTest(chip=chip,align=True):
                c=self.cpu(chip);self.load(c,0x0202)
                self.should_error(c,b'd\x00\x02F\x11\x22 ')
                self.assertEqual(c.erase_count,0)

    def test_eeprom_zero_and_256_length_rejected_before_write(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.load(c,0)
                self.should_error(c,b'd\x01\x00E')
                self.assertEqual(c.eeprom[:32],b'\xff'*32)
                c=self.cpu(chip)
                self.load(c,0)
                self.should_error(c,b'd\x00\x00E')
                self.assertEqual(c.eeprom[:32],b'\xff'*32)

    def test_16_mcusr_reset_cases(self):
        from test_all_mcusr_spm_parity import chip_cpu,with_mcusr
        for chip,(dev,image,obj,_) in self.images.items():
            for reason in range(16):
                with self.subTest(chip=chip,reason=reason):
                    c=with_mcusr(chip_cpu(chip,image,reason),dev)
                    c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
                    expected='boot' if (reason==0 or reason&10==2) else 'app'
                    for i in range(500):
                        if c.pc==c.rxwait_pc:
                            status='boot';break
                        if c.pc==0 or c.app_started:
                            status='app';break
                        c.step()
                    else:self.fail('reset route stalled')
                    self.assertEqual(status,expected)
                    self.assertEqual(c.io[c.mcusr_data_addr],reason&(0xF7 if reason&2 else 0xFF))
                    if expected=='app':self.assertEqual(c.reg[2],reason)

    def test_spm_application_callable_and_boot_guard(self):
        for chip,(dev,img,obj,_) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                original={r:c.reg[r] for r in (*range(2,18),28,29)}
                def call(addr,opcode,data=0):
                    c.reg[24]=addr&255;c.reg[25]=addr>>8
                    c.reg[22]=opcode;c.reg[20]=data&255;c.reg[21]=data>>8
                    c.stack.append(0x0100)
                    c.pc=c.boot_start+2
                    for _ in range(1200):
                        if c.pc==0x0100:
                            self.assertEqual(c.reg[1],0)
                            for r,v in original.items():self.assertEqual(c.reg[r],v)
                            return
                        c.step()
                    self.fail('SPM ABI never returned')
                addr=0xFB00
                c.flash[addr:addr+2]=b'\x00\x00'
                call(addr,3)
                self.assertEqual(c.flash[addr:addr+2],b'\xff\xff')
                call(addr,1,0x3412)
                call(addr,5,0)
                self.assertEqual(c.flash[addr:addr+2],b'\x12\x34')
                before=bytes(c.flash[c.boot_start:])
                for opcode in (1,3,5):call(0xFC00,opcode)
                self.assertEqual(c.flash[c.boot_start:],before)

    def test_reject_wrong_device_in_builder(self):
        completed=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p','--compact-644'],capture_output=True,text=True)
        self.assertNotEqual(completed.returncode,0)
        self.assertIn('only for ATmega644',completed.stderr)
        completed=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega644p','--compact-644','--boot-bytes','512'],capture_output=True,text=True)
        self.assertNotEqual(completed.returncode,0)
        self.assertIn('minimum of 1024 bytes',completed.stderr)

if __name__=='__main__':unittest.main()
