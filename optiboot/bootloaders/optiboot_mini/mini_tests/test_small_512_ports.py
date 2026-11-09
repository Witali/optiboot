#!/usr/bin/env python3
"""Execute the actual compiled 511-byte boot images on all new small AVR ports.

No physical MCU model can prove hardware timing or actual fuse contents. Tests
cover STK500v1 packets, legacy UART registers, SPM ABI, EEPROM, MCUSR and
protection boundaries; image and geometry are checked independently of input.
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini
from test_all_mcusr_spm_parity import chip_cpu,with_mcusr
from test_legacy_uart import symaddr

OLDER=('atmega8','atmega8a','atmega8515','atmega8535','atmega88',
       'atmega88p','atmega16','atmega32a','atmega162')
FIRMWARE=ROOT/'output'/'validation_constants'/'compact'

class SmallBootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images={}
        for chip in OLDER:
            dev=build_mini.DEVICES[chip]
            folder=FIRMWARE/chip
            boot=(folder/(chip+'.bin')).read_bytes()
            obj=folder/(chip+'.o')
            meta=json.loads((folder/(chip+'.json')).read_text())
            cls.images[chip]=(dev,boot,obj,meta)

    def cpu(self,chip,reason=2,do_wait=True):
        dev,boot,obj,meta=self.images[chip]
        c=with_mcusr(chip_cpu(chip,boot,reason),dev)
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        c.error_pc=c.boot_start+symaddr(obj,'error_loop')
        if do_wait:c.wait_ready()
        return c

    @staticmethod
    def addr(c,value):
        return c.send(bytes((0x55,(value>>1)&255,(value>>9)&255,0x20)))

    def invoke(self,c,addr,command,data=0):
        original={r:c.reg[r] for r in tuple(range(2,18))+(28,29)}
        c.io[0x5f]=0x83
        c.reg[24]=addr&255;c.reg[25]=(addr>>8)&255
        c.reg[22]=command;c.reg[20]=data&255;c.reg[21]=(data>>8)&255
        destination=0x0200
        c.stack.append(destination)
        c.pc=c.boot_start+2
        for _ in range(4000):
            if c.pc==destination:
                self.assertEqual(c.reg[1],0)
                self.assertEqual({r:c.reg[r] for r in original},original)
                return
            c.step()
        self.fail(f'SPM callable ABI did not return, pc={c.pc:x}')

    def run_until_error(self,c,pkt):
        c.rx.extend(pkt)
        for _ in range(140000):
            if c.pc==c.error_pc:
                return
            c.step()
        self.fail(f'Invalid packet did not reach watchdog error path, pc={c.pc:x}')

    def test_511_bytes_with_real_512_byte_boot_config(self):
        self.assertEqual(len(OLDER),9)
        for chip,(d,boot,obj,meta) in self.images.items():
            with self.subTest(chip=chip):
                self.assertEqual(len(boot),512)
                self.assertEqual(meta['code_bytes'],498)
                self.assertEqual(meta['footer_bytes'],5)
                self.assertEqual(meta['boot_bytes'],512)
                self.assertEqual(int(meta['boot_start_hex'],16),d['flash']-512)
                self.assertEqual(meta['app_spm_entry_byte_address'],d['flash']-510)
                self.assertEqual(meta['signature_hex'].upper(),''.join('%02X'%v for v in d['sig']))
                self.assertEqual(boot[-5:],bytes(d['sig'])+b'\x03\x08')
                self.assertTrue(meta['stk_universal_signature_0x30'])
                self.assertEqual(symaddr(obj,'optiboot_mini_do_spm'),2)
                self.assertEqual(hashlib.sha256(boot).hexdigest(),meta['bin_sha256'])
                self.assertEqual(meta['bootsz1_0_bits'], '10' if d['flash']<=16384 else '11')

    def test_stk_sync_signatures_version_and_legacy_usart(self):
        for chip,(d,boot,obj,meta) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                if d['profile']=='legacy':
                    self.assertEqual(c.ucsrc,0x86)
                    self.assertEqual(c.ubrrh,0)
                    self.assertEqual(c.ubrrl,16)
                else:
                    self.assertEqual(c.io[0xc1],0x18)
                    self.assertEqual(c.io[0xc4],16)
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'P '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(d['sig'])+b'\x10')
                for idx,v in enumerate(d['sig']):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,idx,0,0x20))),bytes((0x14,v,0x10)))
                self.assertEqual(c.send(bytes((0x56,0x30,0,3,0,0x20))),b'\x14\x00\x10')
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                self.assertEqual(c.send(b'A\x82 '),b'\x14\x03\x10')
                self.assertEqual(c.send(b'1 '),b'\x14\x10') # intentionally no string in compact variant
                self.assertEqual(c.send(b'B'+bytes(20)+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'E'+bytes(5)+b' '),b'\x14\x10')

    def test_flash_pages_eeprom_tail_and_boot_protection(self):
        for chip,(d,boot,obj,meta) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                for addr in (0,c.boot_start-d['page']):
                    payload=bytes((i*29+(addr>>6)*7)&255 for i in range(d['page']))
                    self.assertEqual(self.addr(c,addr),b'\x14\x10')
                    self.assertEqual(c.send(bytes((0x64,0,len(payload),ord('F')))+payload+b' '),b'\x14\x10')
                    self.assertEqual(c.flash[addr:addr+d['page']],payload)
                    self.assertEqual(self.addr(c,addr),b'\x14\x10')
                    self.assertEqual(c.send(bytes((0x74,0,len(payload),ord('F'),0x20))),b'\x14'+payload+b'\x10')
                eaddr=d['eeprom']-16
                ep=bytes((11*i+3)&255 for i in range(16))
                self.assertEqual(self.addr(c,eaddr),b'\x14\x10')
                self.assertEqual(c.send(b'd\x00\x10E'+ep+b' '),b'\x14\x10')
                self.assertEqual(bytes(c.eeprom[eaddr:eaddr+16]),ep)
                self.assertEqual(self.addr(c,eaddr),b'\x14\x10')
                self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+ep+b'\x10')
                self.assertEqual(bytes(c.flash[c.boot_start:]),boot)

    def test_application_spm_abi_and_boot_guard(self):
        for chip,(d,boot,obj,meta) in self.images.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                addr=c.boot_start-d['page']
                c.flash[addr:addr+2]=b'\x00\x00'
                self.invoke(c,addr,3,0)
                self.assertEqual(bytes(c.flash[addr:addr+2]),b'\xff\xff')
                self.invoke(c,addr,1,0x3412)
                self.invoke(c,addr,5,0)
                self.assertEqual(bytes(c.flash[addr:addr+2]),b'\x12\x34')
                self.invoke(c,addr,0x11,0)
                before=bytes(c.flash[c.boot_start:])
                for op in (1,3,5):self.invoke(c,c.boot_start,op,0)
                self.assertEqual(bytes(c.flash[c.boot_start:]),before)

    def test_bad_eop_and_boot_write_do_not_erase(self):
        for chip,(d,boot,obj,meta) in self.images.items():
            with self.subTest(chip=chip):
                page=d['page'];addr=d['flash']-512-page
                c=self.cpu(chip)
                c.flash[addr:addr+page]=b'\xa5'*page
                self.addr(c,addr)
                pkt=bytes((0x64,0,page,ord('F')))+bytes(range(page))+b'!'
                self.run_until_error(c,pkt)
                self.assertEqual(c.erase_count,0)
                self.assertEqual(c.flash[addr:addr+page],b'\xa5'*page)
                c=self.cpu(chip)
                self.addr(c,c.boot_start)
                pkt=bytes((0x64,0,page,ord('F')))+bytes(range(page))+b' '
                self.run_until_error(c,pkt)
                self.assertEqual(c.erase_count,0)
                self.assertEqual(bytes(c.flash[c.boot_start:]),boot)

    def test_mcusr_16_flag_combinations_preserve_cause(self):
        for chip in OLDER:
            for reason in range(16):
                with self.subTest(chip=chip,reason=reason):
                    c=self.cpu(chip,reason,do_wait=False)
                    final='timeout'
                    for _ in range(400):
                        if c.pc==c.rxwait_pc:final='boot';break
                        if c.pc==0 or getattr(c,'app_started',False):final='app';break
                        c.step()
                    self.assertEqual(final,'boot' if reason==0 or reason&10==2 else 'app')
                    self.assertEqual(c.io[c.mcusr_data_addr],reason & (0xF7 if reason&2 else 0xFF))
                    if final=='app':self.assertEqual(c.reg[2],reason)

if __name__=='__main__':unittest.main()
