"""Tests for newly compacted 64A, banked ATmega and virtual-Boot ATtiny.

Executes compiled AVR opcodes in the project's behavioral simulators. Neither
physical UART/SPM timing nor real hardware lock/fuse behavior is simulated.
Run build_mini_compat.py --all first (or this suite builds missing binaries).
"""
from pathlib import Path
import json
import sys
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini
from test_mega64_audit import AVR64
from test_128k import AVR128
from test_expanded_ports import Mega256New
from test_tiny_virtual import TinyAVR
from test_soft_uart import SoftAVR
from test_legacy_uart import symaddr

SMALL=('atmega64a','attiny1634','attiny841')
BANKED=('atmega1284p','atmega128a','atmega2560')
SIZES={'atmega64a':503,'atmega1284p':549,'atmega128a':557,
       'atmega2560':599,'attiny1634':501,'attiny841':505}

class TestNewCompactFamilies(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data={}
        for chip in (*SMALL,*BANKED,'attiny84','attiny85'):
            d=build_mini.DEVICES[chip]
            folder=ROOT/'output'/'r7_matrix'/chip
            if not (folder/(chip+'.json')).exists():
                folder.mkdir(parents=True,exist_ok=True)
                flags=['--compact-banked'] if chip in BANKED else ['--compact-tiny','--mcusr-parity'] if d['virtual_boot'] else ['--compact-64k']
                cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,'--output-dir',str(folder),*flags]
                if chip=='attiny1634':cmd+=['--f-cpu','12000000']
                elif chip in ('attiny84','attiny85'):cmd+=['--f-cpu','8000000','--clock-source','internal_rc']
                subprocess.run(cmd,check=True,capture_output=True,text=True)
            cls.data[chip]=((folder/(chip+'.bin')).read_bytes(),folder/(chip+'.o'),json.loads((folder/(chip+'.json')).read_text()))
    def cpu(self,chip):
        image,obj,_=self.data[chip]
        dev=build_mini.DEVICES[chip]
        if chip=='atmega64a':c=AVR64(image)
        elif chip=='atmega2560':c=Mega256New(image)
        elif chip in BANKED:c=AVR128(image,chip=='atmega128a')
        elif chip in ('attiny841','attiny1634'):c=TinyAVR(image,dev)
        else:c=SoftAVR(image,dev)
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        c.error_pc=c.boot_start+symaddr(obj,'error_loop')
        c.wait_ready()
        return c

    def test_compiled_sizes_and_entry_points(self):
        for chip,size in SIZES.items():
            with self.subTest(chip=chip):
                binary,obj,m=self.data[chip]
                self.assertEqual(m['compact_payload_bytes'],size)
                self.assertEqual(len(binary),512 if chip.startswith('attiny') else 1024)
                self.assertEqual(m['footer_bytes'],5)
                self.assertEqual(binary[-5:],bytes(build_mini.DEVICES[chip]['sig'])+b'\x03\x08')
                if chip.startswith('atmega'):
                    self.assertEqual(symaddr(obj,'optiboot_mini_do_spm'),2)
                    self.assertTrue(m['app_spm'])
                else:
                    self.assertFalse(m['app_spm'])
                    self.assertTrue(m['virtual_boot_vector_patch_required'])
        self.assertTrue(all(self.data[k][2]['payload_under_512'] for k in SMALL))

    def test_atmega64a_compact_uart_eeprom_flash_and_protection(self):
        c=self.cpu('atmega64a')
        self.assertEqual(c.io[0x95],6)
        self.assertEqual(c.io[0x90],0)
        self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
        self.assertEqual(c.send(b'u '),b'\x14\x1e\x96\x02\x10')
        ep=bytes(range(16))
        self.assertEqual(c.load_address(2032),b'\x14\x10')
        self.assertEqual(c.send(b'd\x00\x10E'+ep+b' '),b'\x14\x10')
        self.assertEqual(c.eeprom[-16:],ep)
        self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+ep+b'\x10')
        data=bytes((i*19+7)&255 for i in range(256))
        self.assertEqual(c.load_address(0xFB00),b'\x14\x10')
        self.assertEqual(c.write_flash(data),b'\x14\x10')
        self.assertEqual(c.flash[0xFB00:0xFC00],data)
        self.assertEqual(c.load_address(0xFB00),b'\x14\x10')
        self.assertEqual(c.read_flash(256),b'\x14'+data+b'\x10')
        bad=self.cpu('atmega64a')
        bad.load_address(0xFC00)
        bad.execute_until_error(b'd\x01\x00F'+bytes(256)+b' ',bad.error_pc,limit=200000)
        self.assertEqual(bad.erase_count,0)

    def test_banked_eeprom_and_flash_cross_banks(self):
        for chip in BANKED:
            with self.subTest(chip=chip):
                c=self.cpu(chip);dev=build_mini.DEVICES[chip]
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                ep=bytes((i*31+5)&255 for i in range(16))
                self.assertEqual(c.load_addr(4080) if chip=='atmega2560' else c.load_address(4080),b'\x14\x10')
                self.assertEqual(c.send(b'd\x00\x10E'+ep+b' '),b'\x14\x10')
                self.assertEqual(bytes(c.eeprom[-16:]),ep)
                self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+ep+b'\x10')
                addrs=(0x10000,0x1FB00) if chip!='atmega2560' else (0x10000,0x20000,0x3FB00)
                for addr in addrs:
                    if chip=='atmega2560':
                        self.assertEqual(c.ext_addr(addr>>17),b'\x14\x00\x10')
                        self.assertEqual(c.load_addr(addr),b'\x14\x10')
                    else:
                        self.assertEqual(c.load_address(addr),b'\x14\x10')
                    data=bytes((i*7+addr//256)&255 for i in range(256))
                    self.assertEqual(c.write_flash(data),b'\x14\x10')
                    self.assertEqual(bytes(c.flash[addr:addr+256]),data)
                    self.assertEqual(c.load_addr(addr) if chip=='atmega2560' else c.load_address(addr),b'\x14\x10')
                    self.assertEqual(c.read_flash(256),b'\x14'+data+b'\x10')

    def test_banked_app_spm_abi_and_boot_guard(self):
        for chip in ('atmega64a',*BANKED):
            with self.subTest(chip=chip):
                c=self.cpu(chip);maxbank=c.boot_start>>16
                for bank in (0,maxbank):
                    address=0x0200
                    if bank==maxbank and maxbank==0:continue
                    original={r:c.reg[r] for r in [*range(2,18),28,29]}
                    location=(bank<<16)|address
                    c.flash[location:location+2]=b'\x00\x00'
                    c.reg[24]=0;c.reg[25]=2;c.reg[22]=3;c.reg[20]=c.reg[21]=0
                    if chip!='atmega64a':c.io[0x5b]=bank
                    c.pc=c.boot_start+2;c.stack.append(0x300)
                    for _ in range(1000):
                        if c.pc==0x300:break
                        c.step()
                    else:self.fail('SPM did not RET')
                    self.assertEqual(c.flash[location:location+2],b'\xff\xff')
                    self.assertEqual({r:c.reg[r] for r in original},original)
                    self.assertEqual(c.reg[1],0)
                # A direct SPM call into the Boot area must not erase it.
                addr=c.boot_start&0xffff
                before=bytes(c.flash[c.boot_start:])
                c.reg[24],c.reg[25]=addr&255,addr>>8
                c.reg[22]=3;c.reg[20]=c.reg[21]=0
                if chip!='atmega64a':c.io[0x5b]=maxbank
                c.pc=c.boot_start+2;c.stack.append(0x300)
                for _ in range(1000):
                    if c.pc==0x300:break
                    c.step()
                self.assertEqual(c.flash[c.boot_start:],before)

    def test_tiny_grouped_flash_and_eeprom(self):
        for chip in ('attiny1634','attiny841'):
            with self.subTest(chip=chip):
                c=self.cpu(chip);d=build_mini.DEVICES[chip]
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(d['sig'])+b'\x10')
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                ep=bytes(range(16));addr=d['eeprom']-16
                self.assertEqual(c.load_address(addr),b'\x14\x10')
                self.assertEqual(c.send(b'd\x00\x10E'+ep+b' '),b'\x14\x10')
                self.assertEqual(c.eeprom[addr:],ep)
                group=d['flash_erase_group_bytes'];addr=c.boot_start-group
                page=bytes((i*13+7)&255 for i in range(group))
                self.assertEqual(c.load_address(addr),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x64,0,group,0x46))+page+b' '),b'\x14\x10')
                self.assertEqual(c.flash[addr:addr+group],page)
                self.assertEqual(c.group_erases,[addr])
                self.assertEqual(c.page_writes,list(range(addr+group-d['page'],addr-1,-d['page'])))

    def test_compact_soft_uart_sync(self):
        for chip in ('attiny84','attiny85'):
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.assertEqual(c.f_cpu,8_000_000)
                self.assertEqual(c.baud,19_200)
                c.send_wave(b'0 ')
                self.assertEqual(c.decoded_transmit(),b'\x14\x10')
                c.send_wave(b'u ')
                self.assertEqual(c.decoded_transmit()[-5:],bytes([0x14,*build_mini.DEVICES[chip]['sig'],0x10]))

if __name__=='__main__':unittest.main()
