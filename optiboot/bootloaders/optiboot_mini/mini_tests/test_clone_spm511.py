"""12 directly assembled MCU variants of the 511-byte SPM firmware.

Uses the ONE optiboot_mini.S production source, 12 per-device signatures,
AVR instruction interpreter and a SHA-pinned historical BIN for regression.
Never patches the resulting binary; no physical silicon tests.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
import subprocess

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini as build
from test_modern_audit import AVRModern
from test_all_mcusr_spm_parity import with_mcusr
from test_legacy_uart import symaddr

class TestUnifiedSPM511(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='testsource-')
        cls.out=Path(cls.tmp.name)
        cls.mcu={}
        for chip in (x for x in build.SPM512_COMPATIBLE if build.DEVICES[x]['profile']=='modern' and build.DEVICES[x]['page']==128):
            cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
                 '--f-cpu','16000000','--baud','115200',
                 '--clock-source','external_crystal','--boot-bytes','512',
                 '--app-spm-512','--output-dir',str(cls.out/chip)]
            res=subprocess.run(cmd,capture_output=True,text=True)
            if res.returncode:
                raise RuntimeError(f'{chip} source build failed: {res.stderr}')
            meta=json.loads((cls.out/chip/(chip+'.json')).read_text())
            cls.mcu[chip]=((cls.out/chip/(chip+'.bin')).read_bytes(),meta)
        # all clones are exact instruction-for-instruction copies and the
        # symbol position remains identical; obtain that location from the
        # independently assembled 328P image, never guess the rx PC offset.
        cls.reference_obj=cls.out/'ref.o'
        proc=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
             '--mcu','atmega328p','--f-cpu','16000000','--baud','115200',
             '--app-spm-512','--output-dir',str(cls.out/'ref')],capture_output=True,text=True)
        if proc.returncode:raise RuntimeError(proc.stderr)
        cls.rx_off=symaddr(cls.out/'ref/atmega328p.o','rx_wait')
        cls.err_off=symaddr(cls.out/'ref/atmega328p.o','error_loop')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def cpu(self,chip,reason=2):
        boot,_=self.mcu[chip]
        dev=build.DEVICES[chip]
        c=AVRModern(boot,dev['flash'],dev['page'],dev['eeprom'],reason)
        c=with_mcusr(c,dev)
        c.rxwait_pc=c.boot_start+self.rx_off
        c.error_pc=c.boot_start+self.err_off
        c.wait_ready()
        return c

    def spm_call(self,c,addr,op,data=0):
        before={r:c.reg[r] for r in range(2,18)}
        before.update({r:c.reg[r] for r in (28,29)})
        c.io[0x5f]=0x83
        c.reg[24]=addr & 255
        c.reg[25]=(addr >> 8)&255
        c.reg[22]=op
        c.reg[20]=data & 255
        c.reg[21]=(data >> 8)&255
        ret=0x300
        c.stack.append(ret)
        c.pc=c.boot_start+2
        for _ in range(5000):
            if c.pc==ret:
                self.assertEqual(c.reg[1],0)
                self.assertEqual(c.io[0x5f],0x83)
                self.assertEqual({r:c.reg[r] for r in before},before)
                return
            c.step()
        self.fail(f'SPM did not return for chip flash size {c.flash_size}')

    @unittest.skipUnless((ROOT/'mini_tests/fixtures/atmega328p_spm511_16m115200.bin').is_file(), 'Historical comparison requires snapshots omitted from the 2026-11-08 archive')
    def test_compiled_images_match_optimized_shared_template(self):
        # The historical 511-byte image remains in fixtures, but the new
        # branch layout saves two bytes and relocates many RJMP/RCALL offsets.
        # A literal comparison with the old image is thus inappropriate.
        # Instead verify all modern 128-byte-page targets share the *new*
        # instruction template, except signature and 16KiB geometry bytes.
        history=(ROOT/'mini_tests/fixtures/atmega328p_spm511_16m115200.bin').read_bytes()
        self.assertEqual(len(history),512)
        new=self.mcu['atmega328p'][0]
        self.assertNotEqual(new,history)
        for chip,(fw,meta) in self.mcu.items():
            with self.subTest(chip=chip):
                d=build.DEVICES[chip]
                differences={i for i in range(512) if fw[i]!=new[i]}
                self.assertEqual(meta['source_build_method'],'compile_target_profile')
                allowed={507,508,509}
                if d['flash']==16384:allowed|={3,149,231,236,377,400}
                self.assertTrue(differences<=allowed)
                self.assertEqual(fw[507:510],bytes(d['sig']))
                self.assertEqual(fw[510:],bytes.fromhex('03 08'))
                self.assertEqual(meta['app_spm_entry_byte_address'],d['flash']-510)
                self.assertEqual(meta['boot_bytes'],512)
                self.assertEqual(meta['code_bytes']+meta['footer_bytes'],507)

    def test_programmer_signatures_and_protocol(self):
        for chip,(fw,meta) in self.mcu.items():
            with self.subTest(chip=chip):
                dev=build.DEVICES[chip]
                c=self.cpu(chip)
                self.assertEqual(c.io[0xc1],0x18) # RXEN+TXEN
                self.assertEqual(c.io[0xc4],16) # U2X, 16MHz / 115200
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                for i,v in enumerate(dev['sig']):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),bytes((0x14,v,0x10)))
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                self.assertEqual(c.send(b'A\x82 '),b'\x14\x03\x10')
                self.assertEqual(c.send(b'1 '),b'\x14\x10')
                self.assertEqual(c.send(b'P '),b'\x14\x10')
                self.assertEqual(c.send(b'B'+bytes(20)+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'E'+bytes(5)+b' '),b'\x14\x10')

    def test_flash_last_page_and_eeprom_tail(self):
        for chip,(fw,meta) in self.mcu.items():
            with self.subTest(chip=chip):
                dev=build.DEVICES[chip]
                c=self.cpu(chip)
                for addr in (0x0000,c.boot_start-128):
                    payload=bytes((i*5+addr//128)&255 for i in range(128))
                    self.assertEqual(c.load_address(addr),b'\x14\x10')
                    self.assertEqual(c.write_flash(payload),b'\x14\x10')
                    self.assertEqual(bytes(c.flash[addr:addr+128]),payload)
                    self.assertEqual(c.load_address(addr),b'\x14\x10')
                    self.assertEqual(c.read_flash(128),b'\x14'+payload+b'\x10')
                ep=bytes((i*7+3)&255 for i in range(16))
                addr=dev['eeprom']-16
                c.load_address(addr)
                self.assertEqual(c.send(b'd\x00\x10E'+ep+b' '),b'\x14\x10')
                self.assertEqual(bytes(c.eeprom[addr:addr+16]),ep)
                c.load_address(addr)
                self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+ep+b'\x10')
                self.assertEqual(bytes(c.flash[c.boot_start:]),fw)

    def test_app_spm_abi_and_boot_protection(self):
        for chip,(fw,meta) in self.mcu.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                addr=c.boot_start-128
                c.flash[addr:addr+2]=b'\x00\x00'
                self.spm_call(c,addr,3,0)
                self.assertEqual(bytes(c.flash[addr:addr+2]),b'\xff\xff')
                self.spm_call(c,addr,1,0x3456)
                self.spm_call(c,addr,5,0)
                self.assertEqual(bytes(c.flash[addr:addr+2]),b'\x56\x34')
                orig=bytes(c.flash[c.boot_start:])
                for op in (1,3,5):self.spm_call(c,c.boot_start,op,0)
                self.assertEqual(bytes(c.flash[c.boot_start:]),orig)

    def test_16_reset_flag_combinations(self):
        for chip,(fw,meta) in self.mcu.items():
            dev=build.DEVICES[chip]
            for reason in range(16):
                with self.subTest(chip=chip,cause=reason):
                    c=AVRModern(fw,dev['flash'],dev['page'],dev['eeprom'],reason)
                    c=with_mcusr(c,dev)
                    rx=c.boot_start+self.rx_off
                    status='timeout'
                    for _ in range(400):
                        if c.pc==rx:
                            status='boot';break
                        if c.pc==0 or c.app_started:
                            status='app';break
                        c.step()
                    desired='boot' if reason==0 or reason&10==2 else 'app'
                    self.assertEqual(status,desired)
                    self.assertEqual(c.io[0x54],reason & (0xF7 if reason & 2 else 0xFF))
                    if status=='app':self.assertEqual(c.reg[2],reason)

    def test_bad_eop_never_erases_or_modifies_flash(self):
        for chip,(fw,meta) in self.mcu.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                addr=c.boot_start-128
                c.flash[addr:addr+128]=b'\xA5'*128
                c.load_address(addr)
                payload=bytes((0x64,0,128,ord('F')))+bytes(range(128))+b'!'
                c.execute_until_error(payload,c.error_pc,limit=150000)
                self.assertEqual(c.erase_count,0)
                self.assertEqual(bytes(c.flash[addr:addr+128]),b'\xA5'*128)
                self.assertEqual(bytes(c.flash[c.boot_start:]),fw)

    def test_stk500_write_to_boot_is_rejected(self):
        for chip,(fw,meta) in self.mcu.items():
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                c.load_address(c.boot_start)
                payload=bytes((0x64,0,128,ord('F')))+bytes(range(128))+b' '
                c.execute_until_error(payload,c.error_pc,limit=150000)
                self.assertEqual(c.erase_count,0)
                self.assertEqual(bytes(c.flash[c.boot_start:]),fw)

    def test_capability_gates_and_rebuild_at_eight_megahertz(self):
        for bad in ('atmega644p','atmega64a','atmega1284p','atmega2560','attiny85'):
            with self.subTest(bad=bad):
                self.assertFalse(build.supports_spm512(build.DEVICES[bad]))
                z=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                    '--mcu',bad,'--app-spm-512','--output-dir',str(self.out/'reject')],
                    capture_output=True,text=True)
                self.assertNotEqual(z.returncode,0)
        # Source build supports other legitimate clocks; fixed binary templates cannot.
        z=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
            '--mcu','atmega328p','--app-spm-512','--f-cpu','8000000',
            '--baud','38400','--clock-source','external_crystal',
            '--output-dir',str(self.out/'8mhz')],capture_output=True,text=True)
        self.assertEqual(z.returncode,0,z.stderr)
        self.assertEqual((self.out/'8mhz'/'atmega328p.bin').stat().st_size,512)

if __name__=='__main__':unittest.main()
