#!/usr/bin/env python3
"""R7 shared STK500 tail optimization: size, protocol and memory regressions.

Runs built AVR instructions in the project's software model, comparing R7 to R6.
Does not substitute for hardware-level validation.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT),str(HERE)]
import build_mini
from test_compact_signature_512 import AVRCompact
from test_legacy_uart import symaddr
import test_r5_signon_1024 as signon

BASE = ROOT / 'output/compat_r6_baseline'
NEW = ROOT / 'output/r7_matrix'
BASE_SIGNON = ROOT / 'output/compat_r6_signon'
NEW_SIGNON = ROOT / 'output/r7_signon'
SIGNON = b'\x14AVR STK\x10'


def classic_cpu(folder, chip='atmega328p', mcusr=2):
    base = folder / chip
    im = (base / (chip+'.bin')).read_bytes()
    cpu = AVRCompact(im,mcusr)
    cpu.rxwait_pc = 0x7e00 + symaddr(base/(chip+'.o'),'rx_wait')
    cpu.error_pc = 0x7e00 + symaddr(base/(chip+'.o'),'error_loop')
    for _ in range(600):
        if cpu.pc == cpu.rxwait_pc:
            break
        cpu.step()
    else:
        raise AssertionError('RX polling unreachable')
    return cpu


def signon_cpu(folder, chip):
    with patch.object(signon, 'ROOT_OUT', folder):
        return signon.R5SignOn().cpu(chip)


@unittest.skipUnless((BASE/'matrix.json').is_file(), 'Historical comparison requires snapshots omitted from the 2026-11-08 archive')
class R7SharedTail(unittest.TestCase):
    def test_matrix_preserves_all_features_and_never_increases_size(self):
        old=json.loads((BASE/'matrix.json').read_text())['firmware']
        new=json.loads((NEW/'matrix.json').read_text())['firmware']
        self.assertEqual(len(old),len(new),38)
        changed=[]
        for chip,old_m in sorted(old.items()):
            with self.subTest(chip=chip):
                new_m=new[chip]
                omit={'code_bytes','sha256','boot_start_hex'}
                for name in (
                    'app_spm','app_spm_512','stk_get_sign_on_string',
                    'stk_read_sign_0x75','stk_universal_signature_0x30',
                    'stk_universal_fuse_lock_reads','eeprom_host_addressing',
                    'boot_bytes','bootrst_programmed_required','virtual_boot_vector_patch_required',
                    'flash_page_bytes','flash_bytes','eeprom_bytes','soft_uart',
                    'clock_source','f_cpu_hz','baud_requested',
                ):
                    self.assertEqual(new_m.get(name),old_m.get(name),(chip,name))
                diff=new_m['code_bytes']-old_m['code_bytes']
                self.assertIn(diff,(0,-2))
                old_image=(BASE/chip/(chip+'.bin')).read_bytes()
                new_image=(NEW/chip/(chip+'.bin')).read_bytes()
                if diff==0:
                    self.assertEqual(new_image,old_image,chip)
                else:
                    changed.append(chip)
                    self.assertEqual(new_image[-5:],old_image[-5:])
                self.assertLessEqual(new_m['code_bytes']+new_m['footer_bytes'],new_m['boot_bytes'])
        self.assertEqual(len(changed),29)
        self.assertEqual(new['atmega328p']['code_bytes'],500)
        self.assertEqual(new['atmega328p']['footer_bytes'],5)

    def test_r7_signon_matrix_preserves_all_17_enabled_variants(self):
        old=json.loads((BASE_SIGNON/'matrix.json').read_text())['firmware']
        new=json.loads((NEW_SIGNON/'matrix.json').read_text())['firmware']
        self.assertEqual(len(old),len(new),38)
        normal_old=json.loads((BASE/'matrix.json').read_text())['firmware']
        normal_new=json.loads((NEW/'matrix.json').read_text())['firmware']
        self.assertEqual(sum(m['stk_get_sign_on_string'] for m in new.values()),17)
        for chip,now in new.items():
            with self.subTest(chip=chip):
                was=old[chip]
                self.assertEqual(now['stk_get_sign_on_string'],was['stk_get_sign_on_string'])
                self.assertEqual(now['app_spm'],was['app_spm'])
                self.assertEqual(now['code_bytes']-was['code_bytes'],
                                 normal_new[chip]['code_bytes']-normal_old[chip]['code_bytes'])
                blob=(NEW_SIGNON/chip/(chip+'.bin')).read_bytes()
                if now['stk_get_sign_on_string']:
                    self.assertEqual(blob[-12:],bytes(build_mini.DEVICES[chip]['sig'])+b'AVR STK\x03\x08')
                    self.assertLessEqual(now['code_bytes']+now['footer_bytes'],now['boot_bytes'])
                else:
                    self.assertEqual(blob,(NEW/chip/(chip+'.bin')).read_bytes())

    def test_atmega328p_protocol_differential(self):
        a=classic_cpu(BASE); b=classic_cpu(NEW)
        common=[
            (b'0 ',b'\x14\x10'),
            (b'u ',b'\x14\x1e\x95\x0f\x10'),
            (b'1 ',b'\x14\x10'),
            (b'A\x81 ',b'\x14\x08\x10'),
            (b'A\x82 ',b'\x14\x03\x10'),
            (b'B'+bytes(20)+b' ',b'\x14\x10'),
            (b'E'+bytes(5)+b' ',b'\x14\x10'),
            (b'P ',b'\x14\x10'),
            (b'Z ',b'\x14\x10'),
        ]
        for q,ans in common:
            with self.subTest(q=q):
                self.assertEqual(a.send(q),ans)
                self.assertEqual(b.send(q),ans)
        for ix,val in enumerate((0x1e,0x95,0x0f,0,0)):
            q=bytes((0x56,0x30,0,ix,0,0x20))
            self.assertEqual(a.send(q),b'\x14'+bytes((val,))+b'\x10')
            self.assertEqual(b.send(q),b'\x14'+bytes((val,))+b'\x10')
        for addr in (0x100,0x7d80):
            payload=bytes((i*13+addr//128)%256 for i in range(128))
            qaddr=bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20))
            qwrite=bytes((0x64,0,128,ord('F')))+payload+b' '
            qread=bytes((0x74,0,128,ord('F'),0x20))
            for c in (a,b):
                self.assertEqual(c.send(qaddr),b'\x14\x10')
                self.assertEqual(c.send(qwrite),b'\x14\x10')
                self.assertEqual(c.send(qaddr),b'\x14\x10')
                self.assertEqual(c.send(qread),b'\x14'+payload+b'\x10')
                self.assertEqual(bytes(c.flash[addr:addr+128]),payload)
        for addr in (0,1008):
            payload=bytes((i*7+addr//8)%256 for i in range(16))
            qaddr=bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20))
            qwrite=bytes((0x64,0,16,ord('E')))+payload+b' '
            qread=bytes((0x74,0,16,ord('E'),0x20))
            for c in (a,b):
                self.assertEqual(c.send(qaddr),b'\x14\x10')
                self.assertEqual(c.send(qwrite),b'\x14\x10')
                self.assertEqual(c.send(qread),b'\x14'+payload+b'\x10')
                self.assertEqual(bytes(c.eeprom[addr:addr+16]),payload)
        self.assertEqual(a.flash[:0x7e00],b.flash[:0x7e00])
        self.assertEqual(a.eeprom,b.eeprom)

    def test_bad_eop_does_not_erase(self):
        for folder in (BASE,NEW):
            with self.subTest(which=folder.name):
                c=classic_cpu(folder)
                addr=0x300
                c.flash[addr:addr+128]=b'\x51'*128
                self.assertEqual(c.send(bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20))),b'\x14\x10')
                c.rx.extend(bytes((0x64,0,128,ord('F')))+bytes(range(128))+b'!')
                for _ in range(180000):
                    if c.pc == c.error_pc:
                        break
                    c.step()
                else:
                    self.fail('Invalid CRC_EOP not rejected')
                self.assertEqual(c.erase_count,0)
                self.assertEqual(bytes(c.flash[addr:addr+128]),b'\x51'*128)

    def test_signon_and_signature_r7_three_architectures(self):
        for chip in ('atmega644p','atmega64a','attiny1634','attiny841'):
            with self.subTest(chip=chip):
                expected=bytes(build_mini.DEVICES[chip]['sig'])
                c=signon_cpu(NEW_SIGNON,chip)
                self.assertEqual(c.send(b'1 '),SIGNON)
                self.assertEqual(c.send(b'u '),b'\x14'+expected+b'\x10')
                for ix,v in enumerate(expected):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,ix,0,0x20))),b'\x14'+bytes((v,))+b'\x10')
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                self.assertEqual(c.send(b'1 '),SIGNON)

    def test_signon_eeprom_flash_644p(self):
        a=signon_cpu(BASE_SIGNON,'atmega644p')
        b=signon_cpu(NEW_SIGNON,'atmega644p')
        for c in (a,b):
            self.assertEqual(c.send(b'1 '),SIGNON)
            addr=len(c.eeprom)-16
            payload=bytes((i*19+3)%256 for i in range(16))
            self.assertEqual(c.load_address(addr),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x64,0,16,ord('E')))+payload+b' '),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x74,0,16,ord('E'),0x20))),b'\x14'+payload+b'\x10')
            self.assertEqual(bytes(c.eeprom[addr:]),payload)
            faddr=0x2000
            fp=bytes((i*13+5)%256 for i in range(256))
            self.assertEqual(c.load_address(faddr),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x64,1,0,ord('F')))+fp+b' '),b'\x14\x10')
            self.assertEqual(c.load_address(faddr),b'\x14\x10')
            self.assertEqual(c.send(bytes((0x74,1,0,ord('F'),0x20))),b'\x14'+fp+b'\x10')
        self.assertEqual(a.flash[:0x7e00],b.flash[:0x7e00])
        self.assertEqual(a.eeprom,b.eeprom)

    def test_soft_uart_binary_and_timing_unchanged(self):
        for chip in ('attiny84','attiny85'):
            self.assertEqual((NEW/chip/(chip+'.bin')).read_bytes(),(BASE/chip/(chip+'.bin')).read_bytes())
            self.assertEqual((NEW_SIGNON/chip/(chip+'.bin')).read_bytes(),(BASE_SIGNON/chip/(chip+'.bin')).read_bytes())

if __name__=='__main__':unittest.main()
