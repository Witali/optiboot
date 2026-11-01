"""R11 paired editions: manifest and executable AVR STK500/EEPROM/Flash audit.

Each run builds the exact firmware into a fresh temporary directory.
Simulator tests validate instruction-level behavior but do not model a
physical MCU or electrical UART timing.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(HERE)]

import build_mini
import build_dual
from test_r10_sigrow import SIGRDModel, SIGRDModel128, SIGRDModel256
from test_legacy_uart import LegacyAVR, symaddr
from test_mega64_audit import AVR64
from test_tiny_virtual import TinyAVR

DEST = None


class DualEditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global DEST
        cls.temp = tempfile.TemporaryDirectory(prefix='mini-editions-')
        DEST = Path(cls.temp.name)
        subprocess.run([sys.executable, str(ROOT/'build_dual.py'), '--all',
                        '--edition', 'both', '--jobs', '4', '--output-dir', str(DEST)],
                       capture_output=True, text=True, check=True)
        cls.entries = json.loads((DEST / 'matrix_dual.json').read_text())
        cls.original = json.loads((HERE / 'fixtures' / 'r10_compact_auto_sha256.json').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def make_cpu(self, chip, edition):
        base = DEST / edition / chip
        img = (base / (chip + '.bin')).read_bytes()
        obj = base / (chip + '.o')
        dev = build_mini.DEVICES[chip]
        if chip in ('atmega1284p',):
            c = SIGRDModel128(img, dev)
        elif chip == 'atmega2560':
            c = SIGRDModel256(img, dev)
        elif chip in ('atmega328p','atmega644p'):
            c = SIGRDModel(img, dev)
        elif chip == 'atmega16':
            c = LegacyAVR(img, dev['flash'], dev['sig'])
        elif chip == 'atmega64a':
            c = AVR64(img)
        elif chip in ('attiny841','attiny1634'):
            c = TinyAVR(img, dev)
        else:
            raise AssertionError('No CPU model for ' + chip)
        c.rxwait_pc = c.boot_start + symaddr(obj, 'rx_wait')
        c.error_pc = c.boot_start + symaddr(obj, 'error_loop')
        c.wait_ready()
        return c

    def test_active_edition_policy(self):
        self.assertEqual(set(self.entries['firmware']),
                         {f'{edition}/{chip}' for chip in build_mini.DEVICES
                          for edition in build_dual.available_editions(chip)})
        self.assertEqual(len(self.entries['excluded_profiles']),13)
        for chip, dev in build_mini.DEVICES.items():
            if not dev['virtual_boot'] and dev['hardware_min_boot_bytes']==1024:
                self.assertEqual(build_dual.available_editions(chip),('full',))
                with self.assertRaisesRegex(ValueError, 'COMPACT'):
                    build_dual.build_command(chip,'compact',None)

    def test_matrix_sizes_features_and_artifact_hashes(self):
        self.assertEqual(self.entries['passed'], 63)
        self.assertEqual(self.entries['failed'], 0)
        self.assertEqual(len(self.entries['firmware']), 63)
        for chip, dev in build_mini.DEVICES.items():
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    entry = self.entries['firmware'][f'{edition}/{chip}']
                    folder = DEST / edition / chip
                    blob = (folder/(chip+'.bin')).read_bytes()
                    self.assertEqual(len(blob), entry['boot_bytes'])
                    self.assertLessEqual(entry['payload_bytes'], len(blob))
                    self.assertEqual(hashlib.sha256(blob).hexdigest(),entry['sha256'])
                    self.assertTrue(entry['eeprom_read'] and entry['eeprom_write'])
                    self.assertTrue(entry['flash_read'] and entry['flash_write'])
                    self.assertEqual(entry['get_sign_on'],edition=='full')
                    self.assertEqual(entry['universal_fuse_lock_read'],edition=='full')
                    self.assertEqual(entry['boot_bytes'],1024 if edition=='full'
                        else (1024 if dev['virtual_boot'] else 512))
                    self.assertEqual(entry['app_spm_abi'],not dev['virtual_boot'])

    def test_no_regression_of_all_38_r10_compact_images(self):
        for chip, checksum in self.original.items():
            with self.subTest(chip=chip):
                if 'compact' in build_dual.available_editions(chip):
                    self.assertEqual(self.entries['firmware'][f'compact/{chip}']['sha256'],checksum)
                else:
                    self.assertNotIn(f'compact/{chip}', self.entries['firmware'])

    def test_stk_commands_and_real_eeprom_on_both_editions(self):
        chips=('atmega328p','atmega16','atmega644p','atmega64a','atmega1284p',
               'atmega2560','attiny841','attiny1634')
        for chip in chips:
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    dev = build_mini.DEVICES[chip]
                    c = self.make_cpu(chip,edition)
                    self.assertEqual(c.send(b'0 '),b'\x14\x10')
                    self.assertEqual(c.send(b'A\x81 '),b'\x14\x08\x10')
                    self.assertEqual(c.send(b'u '), b'\x14'+bytes(dev['sig'])+b'\x10')
                    for idx, byte in enumerate(dev['sig']):
                        pkt=bytes((0x56,0x30,0,idx,0,0x20))
                        self.assertEqual(c.send(pkt),bytes((0x14,byte,0x10)))
                    if edition == 'full':
                        self.assertEqual(c.send(b'1 '),b'\x14AVR STK\x10')
                        self.assertEqual(c.send(b'@\x01\x02 '),b'\x14\x10')
                    eeaddr=dev['eeprom']-16
                    payload=bytes((23*i+17)&255 for i in range(16))
                    load=bytes((0x55,(eeaddr>>1)&255,(eeaddr>>9)&255,0x20))
                    self.assertEqual(c.send(load),b'\x14\x10')
                    self.assertEqual(c.send(b'd\x00\x10E'+payload+b' '),b'\x14\x10')
                    self.assertEqual(bytes(c.eeprom[eeaddr:eeaddr+16]),payload)
                    self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+payload+b'\x10')
                    self.assertEqual(c.send(load),b'\x14\x10')
                    self.assertEqual(c.send(b't\x00\x10E '),b'\x14'+payload+b'\x10')

    def test_fuse_lock_mode_matches_edition(self):
        for chip in ('atmega328p','atmega644p','atmega1284p','atmega2560'):
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    c=self.make_cpu(chip,edition)
                    for cmd,val in ((b'VP\x00\x00\x00 ',0x62),
                                    (b'VX\x08\x00\x00 ',0xd9)):
                        wanted=val if edition=='full' else 0
                        self.assertEqual(c.send(cmd),bytes((0x14,wanted,0x10)))
                    self.assertEqual(c.send(b'V\xac\x53\x00\x00 '),b'\x14\x00\x10')

    def test_flash_roundtrip_and_boot_guard(self):
        for chip in ('atmega328p','atmega16','atmega644p','atmega1284p','atmega2560',
                     'attiny841','attiny1634'):
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    dev=build_mini.DEVICES[chip]
                    c=self.make_cpu(chip,edition)
                    n=(dev['flash_erase_group_bytes'] if dev['virtual_boot'] else dev['page'])
                    addr=0x0200
                    payload=bytes((i*19+13)&255 for i in range(n))
                    load=bytes((0x55,(addr>>1)&255,(addr>>9)&255,0x20))
                    self.assertEqual(c.send(load),b'\x14\x10')
                    self.assertEqual(c.send(bytes((0x64,n>>8,n&255,ord('F')))+payload+b' '),b'\x14\x10')
                    self.assertEqual(bytes(c.flash[addr:addr+n]),payload)
                    self.assertEqual(c.send(load),b'\x14\x10')
                    self.assertEqual(c.send(bytes((0x74,n>>8,n&255,ord('F'),0x20))),
                                     b'\x14'+payload+b'\x10')
                    self.assertEqual(c.flash[c.boot_start:],(DEST/edition/chip/(chip+'.bin')).read_bytes())


    def test_invalid_eop_preserves_eeprom_and_flash(self):
        for chip in ('atmega328p','atmega644p','atmega1284p','atmega2560'):
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    c=self.make_cpu(chip,edition)
                    original_eeprom=bytes(c.eeprom)
                    original_flash=bytes(c.flash[:512])
                    self.assertEqual(c.send(b'U\x00\x00 '),b'\x14\x10')
                    packet=b'd\x00\x10E'+bytes(range(16))+b'!'
                    c.execute_until_error(packet,c.error_pc)
                    self.assertEqual(bytes(c.eeprom),original_eeprom)
                    self.assertEqual(bytes(c.flash[:512]),original_flash)
                    c=self.make_cpu(chip,edition)
                    self.assertEqual(c.send(b'U\x00\x00 '),b'\x14\x10')
                    payload=bytes((i*11+7)&255 for i in range(build_mini.DEVICES[chip]['page']))
                    packet=bytes((0x64,len(payload)>>8,len(payload)&255,ord('F')))+payload+b'!'
                    c.execute_until_error(packet,c.error_pc)
                    self.assertEqual(c.erase_count,0)
                    self.assertEqual(bytes(c.flash[:512]),original_flash)

    def test_application_spm_abi_compact_and_full(self):
        for chip in ('atmega328p','atmega644p'):
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    c=self.make_cpu(chip,edition)
                    target=0x0200
                    c.flash[target:target+2]=b'\x00\x00'
                    preserved={r:c.reg[r] for r in (*range(2,18),28,29)}
                    c.reg[24]=target&255
                    c.reg[25]=target>>8
                    c.reg[22]=0x03  # erase page
                    c.reg[20]=0
                    c.reg[21]=0
                    c.stack.append(0x0400)
                    c.pc=c.boot_start+2
                    for _ in range(1200):
                        if c.pc==0x0400:
                            break
                        c.step()
                    else:
                        self.fail(f'{chip}/{edition}: SPM ABI did not return')
                    self.assertEqual(c.flash[target:target+2],b'\xff\xff')
                    for r,val in preserved.items():
                        self.assertEqual(c.reg[r],val,f'{chip}/{edition} r{r}')

    def test_banked_256k_full_only(self):
        chip='atmega2560'
        for edition in build_dual.available_editions(chip):
            with self.subTest(edition=edition):
                c=self.make_cpu(chip,edition)
                for address in (0x10000,0x20000,0x3fb00):
                    data=bytes((i*7+address//256)&255 for i in range(256))
                    self.assertEqual(c.ext_addr(address>>17),b'\x14\x00\x10')
                    self.assertEqual(c.load_addr(address),b'\x14\x10')
                    self.assertEqual(c.write_flash(data),b'\x14\x10')
                    self.assertEqual(c.flash[address:address+256],data)
                    self.assertEqual(c.ext_addr(address>>17),b'\x14\x00\x10')
                    self.assertEqual(c.load_addr(address),b'\x14\x10')
                    self.assertEqual(c.read_flash(256),b'\x14'+data+b'\x10')
                self.assertEqual(c.flash[c.boot_start:],(DEST/edition/chip/(chip+'.bin')).read_bytes())

    def test_software_uart_waveform_for_both_editions(self):
        from test_soft_uart import SoftAVR
        for chip in ('attiny85','attiny84'):
            for edition in build_dual.available_editions(chip):
                with self.subTest(chip=chip,edition=edition):
                    dev=build_mini.DEVICES[chip]
                    folder=DEST/edition/chip
                    image=(folder/(chip+'.bin')).read_bytes()
                    c=SoftAVR(image,dev,baud=19200,f_cpu=8000000)
                    c.rxwait_pc=c.boot_start+symaddr(folder/(chip+'.o'),'rx_wait')
                    c.wait_ready()
                    c.send_wave(b'0 ')
                    self.assertEqual(c.decoded_transmit(),b'\x14\x10')
                    command=b'1 ' if edition=='full' else b'u '
                    c.send_wave(command)
                    expected=(b'\x14AVR STK\x10' if edition=='full'
                              else b'\x14'+bytes(dev['sig'])+b'\x10')
                    self.assertEqual(c.decoded_transmit(),b'\x14\x10'+expected)

    def test_full_legacy_fuse_lock_reads(self):
        for chip in ('atmega16','atmega64a'):
            with self.subTest(chip=chip):
                c=self.make_cpu(chip,'full')
                self.assertEqual(c.send(b'VP\x00\x00\x00 '),b'\x14\x62\x10')
                self.assertEqual(c.send(b'VX\x08\x00\x00 '),b'\x14\xd9\x10')


if __name__ == '__main__':
    unittest.main()
