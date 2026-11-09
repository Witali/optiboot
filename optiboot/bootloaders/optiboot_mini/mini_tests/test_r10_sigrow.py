"""R10 SIGRD+LPM optional signature source: opcode-level tests, no silicon claim.

Checks exact opcode order (OUT SPMCSR, LPM), silicon-row address stride 2,
READ_SIGN, UNIVERSAL, regular Flash and EEPROM after signature reads.
"""
import json
import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT),str(HERE)]
from test_modern_audit import AVRModern
from test_128k import AVR128
from test_expanded_ports import Mega256New
from test_legacy_uart import symaddr
import build_mini

class SIGRDMixin:
    def setup_signature(self, dev, signature=None):
        self.hardware_signature = tuple(signature if signature is not None else dev['sig'])
        self.pending_sigrow = False
        self.sigrow_reads = []

    def io_write(self, addr, val):
        if addr == self.spmcsr and val == 0x21:
            self.pending_sigrow = True
        return super().io_write(addr, val)

    def step(self):
        if self.pending_sigrow:
            op = self.u16(self.pc)
            # The next instruction MUST be LPM Rd,Z or LPM Rd,Z+.
            if (op & 0xfe0f) not in (0x9004, 0x9005):
                raise AssertionError(f'SIGRD: LPM not immediately after SPMCSR write at pc {self.pc:05X}, op={op:04X}')
            z = self.z()
            if z not in (0, 2, 4):
                raise AssertionError(f'SIGRD: invalid signature row Z=0x{z:04X}')
            rd = (op >> 4) & 31
            self.reg[rd] = self.hardware_signature[z//2]
            self.sigrow_reads.append(z)
            if op & 0x0001:
                self.set_z(z+1)
            self.io[self.spmcsr] = 0
            self.pending_sigrow = False
            self.pc = (self.pc+2) % len(self.flash)
            self.cycles += 1
            return
        return super().step()

class SIGRDModel(SIGRDMixin,AVRModern):
    def __init__(self, boot, dev, signature=None):
        super().__init__(boot,dev['flash'],dev['page'],dev['eeprom'])
        self.setup_signature(dev,signature)

class SIGRDModel128(SIGRDMixin,AVR128):
    def __init__(self, boot, dev, signature=None):
        super().__init__(boot,False)
        self.setup_signature(dev,signature)

class SIGRDModel256(SIGRDMixin,Mega256New):
    def __init__(self, boot, dev, signature=None):
        super().__init__(boot)
        self.setup_signature(dev,signature)

class R10SignatureSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.binaries = {}
        for chip,mode in [('atmega328p','--app-spm-512'),('atmega328pb','--app-spm-512'),
                          ('atmega88p','--app-spm-512'),('atmega168p','--app-spm-512'),
                          ('atmega164pa','--app-spm-512'),('atmega324pa','--app-spm-512'),
                          ('atmega644p','--compact-64k'),('atmega644a','--compact-64k'),
                          ('atmega1284p','--compact-banked'),('atmega1284','--compact-banked'),
                          ('atmega2560','--compact-banked')]:
            dest = Path(cls.tmp.name)/chip
            cmd = [sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,mode,
                   '--signature-source','hardware','--output-dir',str(dest)]
            result = subprocess.run(cmd,capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr)
            image = (dest/(chip+'.bin')).read_bytes()
            meta = json.loads((dest/(chip+'.json')).read_text())
            cls.binaries[chip] = (image,dest/(chip+'.o'),build_mini.DEVICES[chip],meta)
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def cpu(self,chip,signature=None):
        image,obj,dev,_ = self.binaries[chip]
        c = (SIGRDModel256(image,dev,signature) if chip=='atmega2560' else
             SIGRDModel128(image,dev,signature) if chip in ('atmega1284p','atmega1284') else
             SIGRDModel(image,dev,signature))
        c.rxwait_pc = c.boot_start + symaddr(obj,'rx_wait')
        c.error_pc = c.boot_start + symaddr(obj,'error_loop')
        c.wait_ready()
        return c

    def test_real_signature_row_stk500(self):
        for chip in self.binaries:
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                sig=bytes(build_mini.DEVICES[chip]['sig'])
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+sig+b'\x10')
                self.assertEqual(c.sigrow_reads,[0,2,4])
                for i,b in enumerate(sig):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),bytes((0x14,b,0x10)))
                self.assertEqual(c.sigrow_reads,[0,2,4,0,2,4])
                for idx in (3,4,255):
                    self.assertEqual(c.send(bytes((0x56,0x30,0,idx,0,0x20))),b'\x14\x00\x10')
                self.assertEqual(len(c.sigrow_reads),6)
                self.assertEqual(c.send(bytes((0x56,0xAC,0x53,0,0,0x20))),b'\x14\x00\x10')

    def test_256k_bank_read_after_signature_row(self):
        chip='atmega2560'
        c=self.cpu(chip)
        dev=build_mini.DEVICES[chip]
        for address in (0x10000,0x20000,0x30000):
            payload=bytes((i*17+(address>>16))&255 for i in range(256))
            c.flash[address:address+256] = payload
            self.assertEqual(c.ext_addr(address>>17),b'\x14\x00\x10')
            self.assertEqual(c.load_addr(address),b'\x14\x10')
            self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
            self.assertEqual(c.read_flash(256),b'\x14'+payload+b'\x10')
            self.assertEqual(c.load_addr(address),b'\x14\x10')
            self.assertEqual(c.read_flash(256),b'\x14'+payload+b'\x10')
        self.assertEqual(c.sigrow_reads,[0,2,4]*3)

    def test_dynamic_silicon_identity_is_not_embedded_footer(self):
        c=self.cpu('atmega328p',signature=(0x1e,0x95,0x16))
        self.assertEqual(c.send(b'u '),bytes.fromhex('14 1e 95 16 10'))
        self.assertEqual(c.send(bytes.fromhex('56 30 00 02 00 20')),bytes.fromhex('14 16 10'))
        image,_,dev,meta=self.binaries['atmega328p']
        self.assertEqual(meta['code_bytes'],508)
        self.assertEqual(meta['footer_bytes'],2)
        self.assertEqual(meta['compact_payload_bytes'],510)
        self.assertEqual(image[-2:],bytes((3,8)))
        self.assertEqual(meta['signature_source'],'hardware')

    def test_signature_reads_do_not_change_eeprom_flash(self):
        for chip in ('atmega328p','atmega88p','atmega168p','atmega164pa','atmega324pa','atmega644a','atmega1284p'):
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                dev=build_mini.DEVICES[chip]
                sig=bytes(dev['sig'])
                self.assertEqual(c.send(b'u '),b'\x14'+sig+b'\x10')
                addr=dev['eeprom']-16
                self.assertEqual(c.load_address(addr),b'\x14\x10')
                value=bytes((i*23+5)&255 for i in range(16))
                self.assertEqual(c.send(b'd\x00\x10E'+value+b' '),b'\x14\x10')
                self.assertEqual(c.eeprom[addr:addr+16],value)
                self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+value+b'\x10')
                last=c.boot_start-dev['page']
                content=bytes((i*17+7)&255 for i in range(dev['page']))
                self.assertEqual(c.load_address(last),b'\x14\x10')
                self.assertEqual(c.write_flash(content),b'\x14\x10')
                self.assertEqual(bytes(c.flash[last:last+dev['page']]),content)
                self.assertEqual(c.load_address(last),b'\x14\x10')
                self.assertEqual(c.read_flash(dev['page']),b'\x14'+content+b'\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+sig+b'\x10')

    def test_silicon_signature_with_signon_and_fuse_reads(self):
        # Non-compact 1 KiB boot with real fuse/lock reads, also sign-on footer.
        dest=Path(self.tmp.name)/'full328'
        result=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p',
                               '--boot-bytes','1024','--universal-signature',
                               '--signature-source','hardware','--output-dir',str(dest)],
                              capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        dev=build_mini.DEVICES['atmega328p']
        image=(dest/'atmega328p.bin').read_bytes()
        c=SIGRDModel(image,dev)
        c.rxwait_pc=c.boot_start + symaddr(dest/'atmega328p.o','rx_wait')
        c.wait_ready()
        self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10')
        self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
        self.assertEqual(c.sigrow_reads,[0,2,4])
        self.assertEqual(c.send(bytes.fromhex('56 50 00 00 00 20')),bytes.fromhex('14 62 10'))
        self.assertEqual(c.send(bytes.fromhex('56 58 08 00 00 20')),bytes.fromhex('14 d9 10'))
        self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10')
        self.assertEqual(image[-9:],b'AVR STK\x03\x08')

    def test_1024_compact_signon_uses_flash_not_sigrow(self):
        for chip,mode in [('atmega644p','--compact-64k'),('atmega1284p','--compact-banked')]:
            dest=Path(self.tmp.name)/('signon_'+chip)
            result=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,
                                   mode,'--compact-sign-on','--signature-source','hardware',
                                   '--output-dir',str(dest)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            image=(dest/(chip+'.bin')).read_bytes()
            dev=build_mini.DEVICES[chip]
            c=SIGRDModel128(image,dev) if chip in ('atmega1284p','atmega1284') else SIGRDModel(image,dev)
            c.rxwait_pc=c.boot_start+symaddr(dest/(chip+'.o'),'rx_wait')
            c.wait_ready()
            self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10')
            self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
            for i,b in enumerate(dev['sig']):
                self.assertEqual(c.send(bytes((0x56,0x30,0,i,0,0x20))),bytes((0x14,b,0x10)))
            self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10')
            self.assertEqual(c.sigrow_reads,[0,2,4,0,2,4])

    def test_auto_selects_hardware_or_constants_by_model(self):
        for chip in ('atmega328p','atmega16'):
            dest=Path(self.tmp.name)/('auto_'+chip)
            result=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),
                                   '--mcu',chip,'--app-spm-512',
                                   '--signature-source','auto','--output-dir',str(dest)],
                                  capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            meta=json.loads((dest/(chip+'.json')).read_text())
            self.assertEqual(meta['signature_source'],
                             'hardware' if chip=='atmega328p' else 'constants')
            if chip=='atmega328p':
                c=SIGRDModel((dest/(chip+'.bin')).read_bytes(),build_mini.DEVICES[chip])
                c.rxwait_pc=c.boot_start+symaddr(dest/(chip+'.o'),'rx_wait')
                c.wait_ready()
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(build_mini.DEVICES[chip]['sig'])+b'\x10')

    def test_hardware_rejected_on_untested_family(self):
        result=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega16',
                               '--app-spm-512','--signature-source','hardware',
                               '--output-dir',str(Path(self.tmp.name)/'legacy')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('not been audited',result.stderr)

    def test_512_signon_still_requires_more_space(self):
        result=subprocess.run([sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p',
                               '--app-spm-512','--compact-sign-on','--signature-source','hardware',
                               '--output-dir',str(Path(self.tmp.name)/'over512')],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('exceed 512 bytes',result.stderr)

if __name__=='__main__':unittest.main()
