#!/usr/bin/env python3
"""Executable tests of the real fixed BOOT_START+2 App SPM entry.

The simulator executes assembled AVR machine instructions. Peripheral timing,
lock-bit programming, external interrupts and physical silicon are NOT modeled.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT))
import build_mini
from test_legacy_uart import LegacyAVR, symaddr
from test_modern_audit import AVRModern
from test_128k import AVR128
from test_expanded_ports import Mega256New

CHIPS = ('atmega16','atmega328p','atmega644p','atmega128a','atmega1284p','atmega2560')

class AppSPMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.images={}
        for chip in CHIPS:
            out=Path(cls.tmp.name)/chip
            subprocess.run([sys.executable,str(ROOT/'build_mini.py'), '--mcu',chip,
                            '--app-spm','--universal-signature','--boot-bytes','1024',
                            '--f-cpu','16000000','--baud','115200',
                            '--output-dir',str(out)],capture_output=True,text=True,check=True)
            cls.images[chip] = ((out/(chip+'.bin')).read_bytes(),out/(chip+'.o'),
                                json.loads((out/(chip+'.json')).read_text()))

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def cpu(self,chip):
        img,obj,manifest = self.images[chip]
        mcu=build_mini.DEVICES[chip]
        if chip=='atmega16':
            c=LegacyAVR(img,mcu['flash'],bytes(mcu['sig']))
        elif chip=='atmega128a':
            c=AVR128(img,True)
        elif chip=='atmega1284p':
            c=AVR128(img,False)
        elif chip=='atmega2560':
            c=Mega256New(img)
        else:
            c=AVRModern(img,mcu['flash'],mcu['page'],mcu['eeprom'])
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        c.error_pc=c.boot_start+symaddr(obj,'error_loop')
        c.wait_ready()
        c.spm_exec_count=0
        orig_spm=c.spm
        def wrapped_spm():
            c.spm_exec_count+=1
            original=c.io[c.spmcsr if hasattr(c,'spmcsr') else 0x57]
            if original==0x09:
                c.io[c.spmcsr if hasattr(c,'spmcsr') else 0x57]=0
            else:
                orig_spm()
        c.spm=wrapped_spm
        return c

    def invoke(self,c,address,opcode,data=0,bank=0):
        regs_before = {r:c.reg[r] for r in range(2,18)}
        regs_before.update({r:c.reg[r] for r in (28,29)})
        sreg_before=0x83
        c.io[0x5f]=sreg_before
        c.reg[24]=address&255;c.reg[25]=(address>>8)&255
        c.reg[22]=opcode;c.reg[20]=data&255;c.reg[21]=(data>>8)&255
        if hasattr(c,'spmcsr') and c.flash_size>65536:
            c.io[0x5b]=bank
        target=0x100
        c.pc=c.boot_start+2
        c.stack.append(target)
        for i in range(12000):
            if c.pc == target:
                self.assertEqual(c.io[0x5f],sreg_before,'SREG not restored')
                self.assertEqual(c.reg[1],0,'r1 must equal zero on C return')
                self.assertEqual({r:c.reg[r] for r in regs_before},regs_before,
                                 'C callee-saved registers were changed')
                return i
            c.step()
        self.fail(f'SPM service did not return, PC={c.pc:05x}, chip={c.flash_size}')

    def test_entry_exactly_boot_start_plus_two(self):
        for chip,(img,obj,manifest) in self.images.items():
            with self.subTest(chip=chip):
                start=int(manifest['boot_start_hex'],16)
                self.assertEqual(manifest['boot_bytes'],1024)
                self.assertTrue(manifest['app_spm'])
                self.assertEqual(manifest['app_spm_entry_byte_address'],start+2)
                self.assertEqual(img[4:6],bytes.fromhex('f894'))
                service=symaddr(obj,'app_spm_service')
                branch=int.from_bytes(img[2:4],'little')
                self.assertEqual(branch&0xf000,0xc000)
                relative=branch&0xfff
                if relative&0x800:relative-=4096
                self.assertEqual((2+2+2*relative),service)

    def test_protocol_not_regressed(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                sig=bytes(build_mini.DEVICES[chip]['sig'])
                self.assertEqual(c.send(b'u '),b'\x14'+sig+b'\x10')
                self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10')
                for idx,v in enumerate(sig):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,idx,0,0x20))),bytes((0x14,v,0x10)))

    def test_flash_fill_erase_write_and_rww(self):
        for chip in CHIPS:
            for bank in (0,1) if chip in ('atmega128a','atmega1284p') else (0,1,3) if chip=='atmega2560' else (0,):
                with self.subTest(chip=chip,bank=bank):
                    c=self.cpu(chip)
                    address=(bank<<16)|0x200
                    # Flash page in app area: initialize to all zeros, then erase.
                    c.flash[address:address+2]=b'\x00\x00'
                    self.invoke(c,0x200,0x03,0,bank)
                    self.assertEqual(c.flash[address:address+2],b'\xff\xff')
                    self.invoke(c,0x200,0x01,0x3412,bank)
                    self.assertEqual(c.page_buf[0],0x12)
                    self.assertEqual(c.page_buf[1],0x34)
                    self.invoke(c,0x200,0x05,0,bank)
                    self.assertEqual(c.flash[address:address+2],b'\x12\x34')
                    self.invoke(c,0x200,0x11,0,bank)
                    self.assertGreaterEqual(c.spm_exec_count,6)
                    self.assertEqual(c.flash[c.boot_start:],self.images[chip][0])
                    if hasattr(c,'spmcsr') and c.flash_size>65536:
                        self.assertEqual(c.io[0x5b],bank,'SPM changed application RAMPZ')

    def test_stk500_flash_and_eeprom_still_work_in_app_spm_image(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                dev=build_mini.DEVICES[chip]
                address=0x400
                page=dev['page']
                data=bytes((i*19+3)&0xff for i in range(page))
                self.assertEqual(c.send(bytes((0x55,(address>>1)&0xff,(address>>9)&0xff,0x20))),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x64,(page>>8)&255,page&255,ord('F')))+data+b' '),b'\x14\x10')
                self.assertEqual(c.flash[address:address+page],data)
                self.assertEqual(c.send(bytes((0x55,(address>>1)&0xff,(address>>9)&0xff,0x20))),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x74,(page>>8)&255,page&255,ord('F'),0x20))),b'\x14'+data+b'\x10')
                eaddress=0x20
                ep=bytes(range(16))
                self.assertEqual(c.send(bytes((0x55,(eaddress>>1)&0xff,(eaddress>>9)&0xff,0x20))),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x64,0,16,ord('E')))+ep+b' '),b'\x14\x10')
                self.assertEqual(c.eeprom[eaddress:eaddress+16],ep)
                self.assertEqual(c.send(bytes((0x74,0,16,ord('E'),0x20))),b'\x14'+ep+b'\x10')

    def test_compiled_inline_call_targets_word_address_correctly(self):
        # Isolated headers supply only integer types and FLASHEND, so the
        # compiler's CALL/ICALL encoding is independent of avr-libc coverage.
        import shutil
        if not shutil.which('clang') or not shutil.which('llvm-objcopy'):
            self.skipTest('clang AVR toolchain unavailable')
        tmp=Path(self.tmp.name)/'callabi'
        (tmp/'avr').mkdir(parents=True,exist_ok=True)
        (tmp/'stdint.h').write_text('typedef unsigned short uint16_t; typedef unsigned char uint8_t; typedef unsigned long uint32_t;\n')
        (tmp/'avr'/'io.h').write_text('#ifndef FLASHEND\n#error missing FLASHEND\n#endif\n')
        (tmp/'t.c').write_text('#include "optiboot_mini_app_spm.h"\nvoid test(uint16_t a,uint16_t data) { optiboot_mini_do_spm(a,1,data); }\n')
        expected={'atmega8':bytes.fromhex('0995'),
                  'atmega328p':bytes.fromhex('0e94013e'),
                  'atmega1284p':bytes.fromhex('0e9401fe'),
                  'atmega2560':bytes.fromhex('0f9401fe')}
        for chip,call in expected.items():
            with self.subTest(chip=chip):
                flashend=build_mini.DEVICES[chip]['flash']-1
                obj=tmp/(chip+'.o');binary=tmp/(chip+'.bin')
                command=['clang','-target','avr','-mmcu='+chip,'-Os','-nostdinc',
                         '-I',str(tmp),'-I',str(ROOT),'-DFLASHEND='+str(flashend),
                         '-DOPTIBOOT_MINI_BOOT_BYTES=1024','-c',str(tmp/'t.c'),'-o',str(obj)]
                subprocess.run(command,check=True,capture_output=True)
                subprocess.run(['llvm-objcopy','-O','binary','-j','.text',str(obj),str(binary)],check=True,capture_output=True)
                code=binary.read_bytes()
                self.assertIn(call,code, 'wrong application SPM call encoding')
                if chip == 'atmega8':
                    self.assertIn(bytes.fromhex('e1e0fee0'),code,
                                  'ICALL Z must contain word address 0x0E01')

    def test_refuse_boot_erase_fill_write_and_unsupported(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                old=bytes(c.flash[c.boot_start:])
                upper=c.boot_start>>16
                addr_low=c.boot_start & 0xffff
                before=c.spm_exec_count
                for cmd in (0x01,0x03,0x05,0x07):
                    self.invoke(c,addr_low,cmd,0,upper)
                self.assertEqual(c.spm_exec_count,before)
                self.assertEqual(c.flash[c.boot_start:],old)
                if upper:
                    # RAMPZ out of range must reject rather than wrap.
                    self.invoke(c,0x0200,0x03,0,upper+1)
                    self.assertEqual(c.spm_exec_count,before)

    def test_spm_last_app_page_still_writable(self):
        for chip in CHIPS:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                page=build_mini.DEVICES[chip]['page']
                last=c.boot_start-page
                bank=last>>16
                low=last&0xffff
                self.invoke(c,low,0x03,0,bank)
                self.invoke(c,low,0x01,0xEDAB,bank)
                self.invoke(c,low,0x05,0,bank)
                self.assertEqual(c.flash[last:last+2],b'\xab\xed')
                self.assertEqual(c.flash[c.boot_start:],self.images[chip][0])

    def test_no_app_spm_on_virtual_or_512(self):
        for args in [('--mcu','atmega328p','--boot-bytes','512'),
                     ('--mcu','attiny85','--boot-bytes','1024')]:
            with self.subTest(args=args):
                command=[sys.executable,str(ROOT/'build_mini.py'),'--app-spm',*args,
                         '--output-dir',str(Path(self.tmp.name)/'invalid')]
                r=subprocess.run(command,capture_output=True,text=True)
                self.assertNotEqual(r.returncode,0)
                self.assertTrue('ERROR:' in r.stderr)

if __name__=='__main__':unittest.main()
