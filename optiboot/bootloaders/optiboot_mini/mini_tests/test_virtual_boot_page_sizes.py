"""Whole-page/whole-erase-group ATtiny Virtual Boot Compact regression tests.

Software emulation only; physical flash/clock/ISP/fuse behavior remains untested.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE),str(ROOT/'tiny')]
import build_mini
from test_tiny_virtual import TinyAVR
from test_soft_uart import SoftAVR
from test_legacy_uart import symaddr
from patch_vectors import TARGETS, allowed_boot_sizes, validate_boot_size, patch_application, rjmp, decode_rjmp
from make_seed import make_seed
from flash_tiny import upload

CONFIG={'attiny841':(512,505,16_000_000,'external_crystal'),
        'attiny1634':(512,501,8_000_000,'external_crystal'),
        'attiny84':(576,549,8_000_000,'internal_rc'),
        'attiny85':(576,549,8_000_000,'internal_rc')}

class VirtualBootSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.artifacts={}
        for chip,(reserve,footprint,freq,clock) in CONFIG.items():
            directory=Path(cls.tmp.name)/chip
            cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
                 '--compact-tiny','--mcusr-parity','--boot-bytes','auto',
                 '--f-cpu',str(freq),'--clock-source',clock,'--baud','auto',
                 '--output-dir',str(directory)]
            proc=subprocess.run(cmd,capture_output=True,text=True)
            if proc.returncode:
                raise AssertionError('Build failed for '+chip+': '+proc.stderr)
            meta=json.loads((directory/(chip+'.json')).read_text())
            cls.artifacts[chip]=((directory/(chip+'.bin')).read_bytes(),
                                 directory/(chip+'.o'),meta,build_mini.DEVICES[chip])
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_auto_finds_smallest_valid_erase_group(self):
        for chip,(expected,payload,_,_) in CONFIG.items():
            with self.subTest(chip=chip):
                blob,obj,meta,dev=self.artifacts[chip]
                self.assertEqual(meta['boot_bytes'],expected)
                self.assertEqual(meta['code_bytes']+meta['footer_bytes'],payload)
                self.assertEqual(len(blob),expected)
                self.assertEqual(meta['boot_start_hex'],f'0x{dev["flash"]-expected:04X}')
                self.assertEqual(expected%dev['page'],0)
                self.assertEqual(expected%dev['flash_erase_group_bytes'],0)
                self.assertTrue(meta['virtual_boot_page_aligned'])
                self.assertTrue(meta['virtual_boot_erase_group_aligned'])
    def test_valid_and_invalid_boot_sizes(self):
        self.assertIn(576,allowed_boot_sizes('attiny85'))
        self.assertNotIn(576,allowed_boot_sizes('attiny1634'))
        for chip in CONFIG:
            with self.subTest(chip=chip):
                group=TARGETS[chip]['erase_group']
                self.assertEqual(validate_boot_size(chip,512),512)
                with self.assertRaisesRegex(ValueError,'whole-erase-group'):
                    validate_boot_size(chip,512+group//2)
    def test_vector_patcher_and_isp_seed_for_non_power_of_two_size(self):
        for chip,(reserve,_,_,_) in CONFIG.items():
            with self.subTest(chip=chip):
                t=TARGETS[chip]
                start=t['flash']-reserve
                reset=rjmp(0,0x100//2,t['flash']//2)
                app={0:reset&255,1:reset>>8,t['vector']*2:0xff,t['vector']*2+1:0xff,
                     start-1:0xA5}
                patched,details=patch_application(app,chip,boot_bytes=reserve)
                self.assertEqual(decode_rjmp(0,patched[0]|(patched[1]<<8),t['flash']//2),start//2)
                seed=make_seed(self.artifacts[chip][0],chip,boot_bytes=reserve)
                self.assertEqual(bytes(seed[start+i] for i in range(reserve)),self.artifacts[chip][0])
                self.assertEqual(decode_rjmp(0,seed[0]|(seed[1]<<8),t['flash']//2),start//2)
                with self.assertRaisesRegex(ValueError,'overlaps'):
                    patch_application({**app,start:0x10},chip,boot_bytes=reserve)
    def _emu(self,chip):
        blob,obj,meta,dev=self.artifacts[chip]
        if chip in ('attiny84','attiny85'):
            c=SoftAVR(blob,dev)
        else:
            c=TinyAVR(blob,dev)
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        c.error_pc=c.boot_start+symaddr(obj,'error_loop')
        c.wait_ready()
        return c
    def test_last_application_group_is_writable_and_readable(self):
        for chip in CONFIG:
            with self.subTest(chip=chip):
                c=self._emu(chip)
                group=TARGETS[chip]['erase_group']
                addr=c.boot_start-group
                data=bytes((i*17+9)&255 for i in range(group))
                if chip in ('attiny84','attiny85'):
                    word=addr//2
                    c.send_wave(bytes((0x55,word&255,word>>8,0x20)))
                    self.assertEqual(c.decoded_transmit()[-2:],b'\x14\x10')
                    c.send_wave(bytes((0x64,0,group,ord('F')))+data+b'\x20',max_instructions=3500000)
                    self.assertEqual(bytes(c.flash[addr:addr+group]),data)
                    c.send_wave(bytes((0x55,word&255,word>>8,0x20)))
                    c.send_wave(bytes((0x74,0,group,ord('F'),0x20)),max_instructions=2500000)
                    self.assertEqual(c.decoded_transmit()[-(group+2):],b'\x14'+data+b'\x10')
                else:
                    self.assertEqual(c.load_address(addr),b'\x14\x10')
                    self.assertEqual(c.write_flash(data),b'\x14\x10')
                    self.assertEqual(bytes(c.flash[addr:addr+group]),data)
                    self.assertEqual(c.load_address(addr),b'\x14\x10')
                    self.assertEqual(c.read_flash(group),b'\x14'+data+b'\x10')
    def test_explicit_non_256_aligned_boot_for_group_erase_tinys(self):
        # If these cores ever grow past 512 B, the first larger erase-group
        # reservation must permit writing the last complete application group.
        for chip,size in [('attiny841',576),('attiny1634',640)]:
            with self.subTest(chip=chip):
                path=Path(self.tmp.name)/(chip+'_larger')
                proc=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                    '--mcu',chip,'--compact-tiny','--mcusr-parity',
                    '--boot-bytes',str(size),'--f-cpu','8000000',
                    '--baud','38400','--clock-source','external_crystal',
                    '--output-dir',str(path)],capture_output=True,text=True)
                self.assertEqual(proc.returncode,0,proc.stderr)
                dev=build_mini.DEVICES[chip]
                blob=(path/(chip+'.bin')).read_bytes()
                c=TinyAVR(blob,dev)
                self.assertEqual(c.boot_start,dev['flash']-size)
                c.rxwait_pc=c.boot_start+symaddr(path/(chip+'.o'),'rx_wait')
                c.error_pc=c.boot_start+symaddr(path/(chip+'.o'),'error_loop')
                c.wait_ready()
                group=dev['flash_erase_group_bytes']
                addr=c.boot_start-group
                data=bytes((i*3+6)&255 for i in range(group))
                c.load_address(addr)
                self.assertEqual(c.write_flash(data),b'\x14\x10')
                self.assertEqual(bytes(c.flash[addr:addr+group]),data)
                before=bytes(c.flash[c.boot_start:])
                c.load_address(c.boot_start)
                c.execute_until_error(bytes((0x64,0,group,ord('F')))+data+b' ',c.error_pc,limit=65000)
                self.assertEqual(bytes(c.flash[c.boot_start:]),before)
                self.assertEqual(c.group_erases,[addr])

    def test_boot_write_refused_without_erase(self):
        # In particular on 0x1DC0 boot starts, code must compare both address bytes.
        for chip in CONFIG:
            with self.subTest(chip=chip):
                c=self._emu(chip)
                group=TARGETS[chip]['erase_group']
                address=c.boot_start
                original=bytes(c.flash[address:])
                data=bytes((i*7+3)&255 for i in range(group))
                if chip in ('attiny84','attiny85'):
                    w=address//2
                    c.send_wave(bytes((0x55,w&255,w>>8,0x20)))
                    packet=bytes((0x64,0,group,ord('F')))+data+b'\x20'
                    start=max(c.cycles+int(c.bitcycles*5),c.rx_end+int(c.bitcycles*5))
                    c.scheduled.append((start,packet))
                    c.rx_end=start+int(len(packet)*10*c.bitcycles)
                    for _ in range(650000):
                        c.step()
                        if c.pc==c.error_pc:
                            break
                    self.assertEqual(c.pc,c.error_pc)
                else:
                    c.load_address(address)
                    c.execute_until_error(bytes((0x64,0,group,ord('F')))+data+b' ',c.error_pc,limit=65000)
                self.assertEqual(bytes(c.flash[address:]),original)
                self.assertEqual(c.erase_count,0)

if __name__=='__main__':unittest.main()
