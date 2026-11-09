#!/usr/bin/env python3
"""All 38 variants of upstream-compatible MCUSR; callable SPM on 34 ATmega only.

Executes actual AVR machine instructions. Modeling limitations:
* no physical MCU, oscillator drift, ISP fuses/lock bits or real interrupt timing;
* ATtiny1634 erase of four adjacent pages is modeled explicitly;
* virtual boot mode requires external reset-vector patching and SELFPRGEN.
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path[:0]=[str(HERE),str(ROOT)]
import build_mini
from test_legacy_uart import symaddr
from test_expanded_ports import LegacyNew, Mega256New
from test_modern_audit import AVRModern
from test_128k import AVR128
from test_mega64_audit import AVR64
from test_tiny_virtual import TinyAVR
from test_soft_uart import SoftAVR

BUILD=ROOT/'output'/'validation_constants'

def chip_cpu(chip,image,cause=2):
    dev=build_mini.DEVICES[chip]; profile=dev['profile']
    if profile=='legacy':return LegacyNew(image,dev,cause)
    if profile=='modern':return AVRModern(image,dev['flash'],dev['page'],dev['eeprom'],cause)
    if profile=='modern128':return AVR128(image,False,cause)
    if profile=='modern256':return Mega256New(image,cause)
    if profile=='mega128':return AVR128(image,True,cause)
    if profile=='mega64':return AVR64(image,cause)
    if profile.startswith('soft'):return SoftAVR(image,dev,cause)
    if profile in ('tiny841','tiny1634'):return TinyAVR(image,dev,cause)
    raise AssertionError('Unknown profile '+profile)

class StickyMCUSR:
    """Write-zero-to-clear in MCUSR, including ATtiny1634 at I/O 0x35."""
    def io_write(self,addr,val):
        if addr==self.mcusr_data_addr:
            v=self.io.get(addr,0)
            self.io[addr]=v&(val&255)
            self.mcusr_writes.append((v,val&255,self.io[addr]))
            return
        return super().io_write(addr,val)

def with_mcusr(cpu,dev):
    # Use dynamic class; no modification of core emulator shared by other tests.
    cpu.__class__=type('MCUSR'+cpu.__class__.__name__,(StickyMCUSR,cpu.__class__),{})
    cpu.mcusr_data_addr=0x55 if dev['profile']=='tiny1634' else 0x54
    cpu.mcusr_writes=[]
    return cpu

class ParityAcross38(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.all={}
        summary=json.loads((BUILD/'matrix_dual.json').read_text())
        if summary['passed']!=63 or summary['failed']:
            raise AssertionError('Run run_tests.py to build the constant-signature matrix')
        for chip,d in build_mini.DEVICES.items():
            edition='compact' if d.get('dual_compact_enabled',True) else 'full'
            o=BUILD/edition/chip
            cls.all[chip]=((o/(chip+'.bin')).read_bytes(),o/(chip+'.o'),
                           json.loads((o/(chip+'.json')).read_text()))
    def create(self,chip,cause=2):
        boot,obj,meta=self.all[chip]
        dev=build_mini.DEVICES[chip]
        c=with_mcusr(chip_cpu(chip,boot,cause),dev)
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        return c
    def invoke(self,c,addr,cmd,data=0,bank=0):
        saved={r:c.reg[r] for r in list(range(2,18))+[28,29]}
        sreg=0x83;c.io[0x5f]=sreg
        c.reg[24]=addr&255;c.reg[25]=(addr>>8)&255
        c.reg[22]=cmd;c.reg[20]=data&255;c.reg[21]=(data>>8)&255
        if c.flash_size>65536:c.io[0x5b]=bank
        dest=0x0100
        c.pc=c.boot_start+2;c.stack.append(dest)
        for steps in range(2000):
            if c.pc==dest:
                self.assertEqual(c.reg[1],0)
                self.assertEqual(c.io[0x5f],sreg)
                for r,old in saved.items():self.assertEqual(c.reg[r],old,f'r{r} modified')
                return steps
            c.step()
        self.fail(f'CALL to SPM did not return, pc={c.pc:x}')

    def test_all_38_mcusr_reasons_preserve_flags_and_r2(self):
        for chip,(_,obj,meta) in self.all.items():
            dev=build_mini.DEVICES[chip]
            self.assertEqual(meta['boot_bytes'],576 if chip in ('attiny84','attiny85') else 512 if dev['virtual_boot'] or chip in build_mini.SPM512_COMPATIBLE else 1024)
            self.assertEqual(meta['source_build_method'],'compile_target_profile')
            for reason in range(16):
                with self.subTest(chip=chip,reason=reason):
                    c=self.create(chip,reason)
                    target=('boot' if reason==0 or reason&0x0a==0x02 else 'app')
                    final='timeout'
                    for i in range(300):
                        if c.pc==c.rxwait_pc:
                            final='boot';break
                        if (c.pc==0 or getattr(c,'app_started',False)):
                            final='app';break
                        # The app vector table is intentionally not present in
                        # boot-only firmware; stop before fetching unprogrammed
                        # EEPROM-ready redirect code (created by patch_vectors).
                        if dev['virtual_boot'] and c.pc=={
                            'attiny85':6,'attiny84':14,
                            'attiny841':14,'attiny1634':26}[chip]*2:
                            final='app';break
                        c.step()
                    self.assertEqual(final,target,(chip,reason,hex(c.pc)))
                    expected=reason & (0xf7 if reason&0x02 else 0xff)
                    self.assertEqual(c.io[c.mcusr_data_addr],expected,(chip,reason))
                    if target=='app':self.assertEqual(c.reg[2],reason,(chip,reason))
                    if reason&2:self.assertEqual(len(c.mcusr_writes),1)
                    else:self.assertEqual(len(c.mcusr_writes),0)

    def test_boot_service_abi_layout_and_footer(self):
        for chip,(boot,obj,meta) in self.all.items():
            with self.subTest(chip=chip):
                virtual=build_mini.DEVICES[chip]['virtual_boot']
                self.assertTrue(meta['stk_universal_signature_0x30'])
                self.assertEqual(boot[-2:],b'\x03\x08')
                self.assertLessEqual(meta['code_bytes']+meta['footer_bytes'],len(boot))
                if virtual:
                    self.assertFalse(meta['app_spm'])
                    self.assertIsNone(meta['app_spm_entry_byte_address'])
                    self.assertEqual(meta['application_self_programming'],'direct_spm_whole_flash')
                    self.assertEqual(boot[:2],b'\xf8\x94', 'Virtual Boot starts with CLI, NOT an SPM trampoline')
                    self.assertIsNone(__import__('re').search(r'\boptiboot_mini_do_spm\b',
                        __import__('subprocess').check_output(['llvm-objdump','-t',str(obj)],text=True)))
                else:
                    self.assertTrue(meta['app_spm'])
                    self.assertEqual(meta['app_spm_entry_byte_address'],meta['flash_bytes']-len(boot)+2)
                    self.assertEqual(symaddr(obj,'optiboot_mini_do_spm'),2)
                    self.assertEqual((boot[1]&0xf0),0xc0)

    def test_all_34_atmega_spm_write_read_and_protected_boot(self):
        for chip,(boot,obj,meta) in self.all.items():
            if build_mini.DEVICES[chip]['virtual_boot']:
                continue  # No app-callable ABI on ATtiny, direct instruction works instead
            with self.subTest(chip=chip):
                dev=build_mini.DEVICES[chip]
                c=self.create(chip)
                # Software model of SPM, independent of transport.
                existing_spm=c.spm
                c.spm_count=0
                def counted():
                    c.spm_count+=1
                    return existing_spm()
                c.spm=counted
                addr=0x0200
                c.flash[addr:addr+2]=b'\x00\x00'
                self.invoke(c,addr,0x03,0)
                self.assertEqual(bytes(c.flash[addr:addr+2]),b'\xff\xff')
                self.invoke(c,addr,0x01,0x3412)
                self.invoke(c,addr,0x05,0)
                self.assertEqual(bytes(c.flash[addr:addr+2]),b'\x12\x34')
                # Existing ATmega RWW API call remains available.
                self.invoke(c,0xffff,0x11,0)
                # Boot-area SPM is protected by our ATmega service.
                start=c.spm_count
                ba=c.boot_start
                for opcode in (0x01,0x03,0x05):
                    self.invoke(c,ba&0xffff,opcode,0,ba>>16)
                self.assertEqual(c.spm_count,start)
                self.assertEqual(bytes(c.flash[c.boot_start:]),boot)

    def test_all_4_tiny_direct_spm_from_application(self):
        # The AVR106 hardware rule: on ATtiny without Boot section, SPM is
        # executable anywhere in Flash, provided SELFPRGEN is programmed.
        # Emulates executing a *real instruction* at an application PC,
        # not calling any bootloader symbol. Not a substitute for silicon.
        for chip,(boot,obj,meta) in self.all.items():
            if not build_mini.DEVICES[chip]['virtual_boot']:
                continue
            with self.subTest(chip=chip):
                c=self.create(chip)
                code_addr=0x0200
                target=0x0300
                c.flash[code_addr:code_addr+2]=b'\xe8\x95'  # SPM opcode
                def issue(cmd,data=0):
                    c.pc=code_addr
                    c.reg[30]=target&255;c.reg[31]=target>>8
                    c.reg[0]=data&255;c.reg[1]=data>>8
                    c.io[c.spmcsr]=cmd
                    c.step()
                c.flash[target:target+2]=b'\x00\x00'
                issue(3)
                self.assertEqual(c.flash[target:target+2],b'\xff\xff')
                issue(1,0x3456)
                issue(5)
                self.assertEqual(c.flash[target:target+2],b'\x56\x34')

    def test_tiny_direct_spm_is_not_hardware_boot_protected(self):
        # Negative/safety test: an app's direct SPM can erase Boot bytes.
        # The bootloader's serial handler itself still checks writes.
        chip='attiny85';c=self.create(chip)
        code_addr=0x0200
        c.flash[code_addr:code_addr+2]=b'\xe8\x95'
        self.assertNotEqual(c.flash[c.boot_start:c.boot_start+64],b'\xff'*64)
        c.pc=code_addr;c.reg[30]=c.boot_start&255;c.reg[31]=c.boot_start>>8
        c.io[c.spmcsr]=3
        c.step()
        self.assertEqual(c.flash[c.boot_start:c.boot_start+64],b'\xff'*64)

    def test_tiny_app_spm_trampoline_opt_in_is_rejected(self):
        import subprocess
        for chip in ('attiny84','attiny85','attiny841','attiny1634'):
            for opt in ('--app-spm','--virtual-app-spm'):
                with self.subTest(chip=chip,opt=opt):
                    p=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                        '--mcu',chip,opt,'--output-dir',str(BUILD/'reject-test')],
                        capture_output=True,text=True)
                    self.assertNotEqual(p.returncode,0)
                    self.assertIn('ERROR',p.stderr)

    def test_protocol_hardware_uart_smoke(self):
        for chip,(boot,obj,meta) in self.all.items():
            dev=build_mini.DEVICES[chip]
            if dev['profile'].startswith('soft'):continue
            with self.subTest(chip=chip):
                c=self.create(chip)
                c.wait_ready()
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10' if meta['stk_get_sign_on_string'] else b'\x14\x10')
                for idx,val in enumerate(dev['sig']):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,idx,0,0x20))),bytes((0x14,val,0x10)))

if __name__=='__main__':unittest.main()
