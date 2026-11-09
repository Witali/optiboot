"""R4 shared-kernel reductions: size audit and behavior vs preserved R3.

The two changes are (1) discard_and_verify falls into verify_eop for
ALL profiles; (2) compact banked EEPROM lengths 1..16 use one range test.
Software opcode models only; this is not a hardware timing/ISP test.
"""
import json
import sys
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(ROOT),str(HERE)]
from test_128k import AVR128
from test_mega64_audit import AVR64
from test_expanded_ports import Mega256New
from test_legacy_uart import symaddr

BANKED={'atmega1280','atmega1281','atmega1284','atmega1284p','atmega128a','atmega2560','atmega2561'}

@unittest.skipUnless((ROOT/'output/compat_r3/matrix.json').is_file(), 'Historical comparison requires snapshots omitted from the 2026-11-08 archive')
class SharedCoreR4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous=ROOT/'output'/'compat_r3'
        cls.current=ROOT/'output'/'compat'
        cls.old=json.loads((cls.previous/'matrix.json').read_text())['firmware']
        cls.new=json.loads((cls.current/'matrix.json').read_text())['firmware']

    def test_all_thirty_eight_images_smaller_without_losing_footer_or_abi(self):
        self.assertEqual(len(self.old),38)
        self.assertEqual(set(self.old),set(self.new))
        for chip,old in self.old.items():
            with self.subTest(chip=chip):
                new=self.new[chip]
                reduction=4 if chip in BANKED else 2
                self.assertEqual(old['code_bytes']-new['code_bytes'], reduction)
                self.assertEqual(new['code_bytes']+new['footer_bytes'],
                                 old['code_bytes']+old['footer_bytes']-reduction)
                for field in ('boot_bytes','boot_start_hex','footer_bytes','app_spm',
                              'stk_universal_signature_0x30','eeprom_bytes','flash_page_bytes'):
                    self.assertEqual(new[field],old[field],(chip,field))
                a=(self.previous/chip/(chip+'.bin')).read_bytes()
                b=(self.current/chip/(chip+'.bin')).read_bytes()
                self.assertNotEqual(a,b)
                self.assertEqual(a[-new['footer_bytes']:],b[-new['footer_bytes']:])
                self.assertEqual(len(a),len(b))

    @staticmethod
    def cpu(chip,root):
        p=root/chip
        image=(p/(chip+'.bin')).read_bytes()
        cpu=AVR128(image,chip=='atmega128a')
        cpu.rxwait_pc=cpu.boot_start+symaddr(p/(chip+'.o'),'rx_wait')
        cpu.error_pc=cpu.boot_start+symaddr(p/(chip+'.o'),'error_loop')
        cpu.wait_ready()
        return cpu

    @staticmethod
    def msg_read(length,kind):
        return bytes((0x74,length>>8,length&255,ord(kind),0x20))

    @staticmethod
    def msg_write(data,kind):
        return bytes((0x64,len(data)>>8,len(data)&255,ord(kind)))+data+b'\x20'

    def test_r3_r4_serial_and_storage_transcripts_match(self):
        # Compare exact output and memory mutations after each transaction.
        for chip in ('atmega1284p','atmega128a'):
            with self.subTest(chip=chip):
                a=self.cpu(chip,self.previous)
                b=self.cpu(chip,self.current)
                payload=bytes((i*23+3)&255 for i in range(16))
                program=bytes((i*31+11)&255 for i in range(256))
                commands=[
                    b'0 ',b'A\x81 ',b'A\x82 ',b'u ',
                    b'V\x30\x00\x01\x00 ',
                    b'B'+bytes(20)+b' ',
                    b'E'+bytes(5)+b' ',
                    b'\x55\xf0\x07\x20', # EEPROM byte address 0xFE0
                    self.msg_write(payload,'E'),self.msg_read(16,'E'),
                    b'\x55\x00\x40\x20', # Flash 0x8000
                    self.msg_write(program,'F'),self.msg_read(256,'F'),
                    b'\x77\x20', # unrecognised command, no payload
                ]
                for packet in commands:
                    self.assertEqual(a.send(packet),b.send(packet), (chip,packet))
                    self.assertEqual(a.eeprom,b.eeprom)
                    self.assertEqual(a.flash[:a.boot_start],b.flash[:b.boot_start])
                    self.assertEqual(a.flash[a.boot_start:], (self.previous/chip/(chip+'.bin')).read_bytes())
                    self.assertEqual(b.flash[b.boot_start:], (self.current/chip/(chip+'.bin')).read_bytes())
                    self.assertEqual(a.erase_count,b.erase_count)

    def test_full_256_page_profiles_match_r3_and_guard_eeprom_lengths(self):
        # The biased length check also replaces redundant high/low-byte
        # checks in noncompact wide-branch ATmega64A/128A/2560 builds.
        for chip,size in (('atmega64a',2048),('atmega128a',4096),('atmega2560',4096)):
            def load(which):
                folder=ROOT/'output'/which/chip
                boot=(folder/(chip+'.bin')).read_bytes()
                cpu=(AVR64(boot) if chip=='atmega64a' else
                     Mega256New(boot) if chip=='atmega2560' else AVR128(boot,True))
                cpu.rxwait_pc=cpu.boot_start+symaddr(folder/(chip+'.o'),'rx_wait')
                cpu.error_pc=cpu.boot_start+symaddr(folder/(chip+'.o'),'error_loop')
                cpu.wait_ready()
                return cpu
            for length in (0,17,255,256):
                with self.subTest(chip=chip,length=length):
                    cpu=load('noncompact_r4')
                    cpu.load_address(size-16)
                    cpu.execute_until_error(bytes((0x64,length>>8,length&255,0x45)),cpu.error_pc)
                    self.assertEqual(cpu.eeprom,b'\xff'*size)
                    self.assertEqual(cpu.erase_count,0)
            for length in (1,16):
                with self.subTest(chip=chip,length=length):
                    prev=load('noncompact_r3')
                    curr=load('noncompact_r4')
                    data=bytes((i*17+length)&255 for i in range(length))
                    addr=size-16
                    for pkt in (bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20)),
                                self.msg_write(data,'E'),self.msg_read(length,'E')):
                        self.assertEqual(prev.send(pkt),curr.send(pkt))
                        self.assertEqual(prev.eeprom,curr.eeprom)
                    self.assertEqual(curr.eeprom[addr:addr+length],data)

    def test_banked_eeprom_rejects_invalid_lengths_and_keeps_bounds(self):
        for chip in ('atmega1284p','atmega128a'):
            for length in (0,17,255,256):
                with self.subTest(chip=chip,length=length):
                    cpu=self.cpu(chip,self.current)
                    cpu.load_address(4096-16)
                    cpu.execute_until_error(bytes((0x64,length>>8,length&255,ord('E'))),cpu.error_pc)
                    self.assertEqual(bytes(cpu.eeprom),b'\xff'*4096)
                    self.assertEqual(cpu.erase_count,0)
            for length in (1,16):
                with self.subTest(chip=chip,length=length):
                    cpu=self.cpu(chip,self.current)
                    addr=4096-length
                    # Host protocol uses even byte addresses; 1-byte case starts at 4094.
                    if addr&1:addr-=1
                    data=bytes((j*13+length)&255 for j in range(length))
                    self.assertEqual(cpu.load_address(addr),b'\x14\x10')
                    self.assertEqual(cpu.send(self.msg_write(data,'E')),b'\x14\x10')
                    self.assertEqual(cpu.eeprom[addr:addr+length],data)
                    self.assertEqual(cpu.send(self.msg_read(length,'E')),b'\x14'+data+b'\x10')

if __name__=='__main__':unittest.main()
