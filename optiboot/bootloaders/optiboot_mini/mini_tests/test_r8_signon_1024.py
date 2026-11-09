"""R8 GET_SIGN_ON exact AVR061 response on compact 1024-byte MCU profiles.

Instruction-level tests, not silicon or serial-electrical validation. R4 code
path remains the baseline for all 512-byte BOOTSZ devices.
"""
from pathlib import Path
import json,sys,unittest,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_mini
from test_modern_audit import AVRModern
from test_mega64_audit import AVR64
from test_128k import AVR128
from test_expanded_ports import Mega256New
from test_tiny_virtual import TinyAVR
from test_soft_uart import SoftAVR
from test_legacy_uart import symaddr
from test_all_mcusr_spm_parity import with_mcusr

SIGNON=b'\x14AVR STK\x10'
ROOT_OUT=ROOT/'r8_signon'
ORIG_OUT=ROOT/'r8_all'

@unittest.skipUnless((ROOT_OUT/'matrix.json').is_file(), 'Historical comparison requires snapshots omitted from the 2026-11-08 archive')
class R8SignOn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results=json.loads((ROOT_OUT/'matrix.json').read_text())['firmware']

    def cpu(self,chip):
        dev=build_mini.DEVICES[chip]
        folder=ROOT_OUT/chip
        binary=(folder/(chip+'.bin')).read_bytes()
        if chip in ('atmega644p','atmega640'):
            c=with_mcusr(AVRModern(binary,dev['flash'],dev['page'],dev['eeprom']),dev)
        elif chip=='atmega64a':
            c=AVR64(binary)
        elif chip=='atmega128a':
            c=AVR128(binary,True)
        elif chip=='atmega1284p':
            c=AVR128(binary,False)
        elif chip=='atmega2560':
            c=Mega256New(binary)
        elif chip in ('attiny841','attiny1634'):
            c=TinyAVR(binary,dev)
        elif chip in ('attiny84','attiny85'):
            c=SoftAVR(binary,dev)
        else:raise ValueError(chip)
        c.rxwait_pc=c.boot_start+symaddr(folder/(chip+'.o'),'rx_wait')
        c.error_pc=c.boot_start+symaddr(folder/(chip+'.o'),'error_loop')
        c.wait_ready()
        return c

    def test_full_matrix_and_footer(self):
        self.assertEqual(len(self.results),38)
        self.assertEqual(sum(v['stk_get_sign_on_string'] for v in self.results.values()),17)
        for chip,v in self.results.items():
            with self.subTest(chip=chip):
                dev=build_mini.DEVICES[chip]
                image=(ROOT_OUT/chip/(chip+'.bin')).read_bytes()
                old=(ORIG_OUT/chip/(chip+'.bin')).read_bytes()
                self.assertEqual(len(image),len(old))
                self.assertEqual(image[-2:],b'\x03\x08')
                if v['stk_get_sign_on_string']:
                    self.assertEqual(image[-12:],bytes(dev['sig'])+b'AVR STK\x03\x08')
                    self.assertLess(v['code_bytes']+v['footer_bytes'],1024)
                else:
                    self.assertEqual(image,old,chip)
                    self.assertEqual(len(image),512)
                    self.assertEqual(image[-5:],bytes(dev['sig'])+b'\x03\x08')

    def test_exact_response_all_architectures(self):
        for chip in ('atmega644p','atmega640','atmega64a','atmega128a','atmega1284p',
                     'atmega2560','attiny841','attiny1634'):
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'1 '),SIGNON)
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(build_mini.DEVICES[chip]['sig'])+b'\x10')
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                self.assertEqual(c.send(b'1 '),SIGNON)
                self.assertEqual(c.send(b'B'+bytes(20)+b' '),b'\x14\x10')

    def test_eeprom_after_signon(self):
        for chip in ('atmega644p','atmega64a','atmega1284p','atmega2560','attiny841','attiny1634'):
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.assertEqual(c.send(b'1 '),SIGNON)
                addr=(len(c.eeprom)-16)&~1
                self.assertEqual(c.load_address(addr),b'\x14\x10')
                payload=bytes((n*17+5)&255 for n in range(16))
                self.assertEqual(c.send(b'd\x00\x10E'+payload+b' '),b'\x14\x10')
                self.assertEqual(bytes(c.eeprom[addr:addr+16]),payload)
                self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+payload+b'\x10')

    def test_flash_after_signon_multiple_geometries(self):
        for chip,addr,page in (('atmega644p',0x2000,256),
                               ('atmega1284p',0x2000,256),
                               ('atmega2560',0x2000,256),
                               ('attiny841',0x0800,64),
                               ('attiny1634',0x0800,128)):
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                self.assertEqual(c.send(b'1 '),SIGNON)
                data=bytes((i*19+7)&255 for i in range(page))
                self.assertEqual(c.load_address(addr),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x64,page>>8,page&255,ord('F')))+data+b' '),b'\x14\x10')
                self.assertEqual(bytes(c.flash[addr:addr+page]),data)
                self.assertEqual(c.load_address(addr),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x74,page>>8,page&255,ord('F'),0x20))),b'\x14'+data+b'\x10')
                self.assertEqual(c.erase_count,1)

    def test_soft_uart_signon_waveform(self):
        for chip in ('attiny84','attiny85'):
            with self.subTest(chip=chip):
                c=self.cpu(chip)
                c.send_wave(b'1 ')
                self.assertEqual(c.decoded_transmit(),SIGNON)
                c.send_wave(b'0 ')
                self.assertEqual(c.decoded_transmit()[-2:],b'\x14\x10')

    def test_512_profile_must_not_expand_or_disable_spm_abi(self):
        with tempfile.TemporaryDirectory() as tmp:
            cmd=[sys.executable,str(ROOT/'build_mini.py'),
                 '--mcu','atmega328p','--app-spm-512','--compact-sign-on',
                 '--f-cpu','16000000','--baud','115200','--output-dir',tmp]
            proc=subprocess.run(cmd,capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0)
            self.assertIn('520 bytes exceed 512 bytes',proc.stderr)
            baseline=self.results['atmega328p']
            self.assertTrue(baseline['app_spm'])
            self.assertFalse(baseline['stk_get_sign_on_string'])
            self.assertLessEqual(baseline['code_bytes']+baseline['footer_bytes'],512)

    def test_bad_eop_fails_before_signon(self):
        chip='atmega644p'
        c=self.cpu(chip)
        c.execute_until_error(b'1!',c.error_pc)
        self.assertEqual(bytes(c.tx),b'')
        self.assertEqual(c.erase_count,0)
        self.assertEqual(bytes(c.flash[c.boot_start:]),(ROOT_OUT/chip/(chip+'.bin')).read_bytes())

if __name__=='__main__':unittest.main()
