"""Test unified per-architecture compilation without binary cloning."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import build_mini

class UnifiedFirmwareTests(unittest.TestCase):
    def test_only_one_active_firmware_assembly(self):
        self.assertEqual(sorted(v.name for v in ROOT.glob('*.S')),
                         ['optiboot_mini.S', 'optiboot_mini328.S'])
        # mini328 is the preserved fixed reference, outside the edition builder.
        self.assertIn("SOURCE = ROOT / 'optiboot_mini.S'",(ROOT/'build_mini.py').read_text())
        self.assertNotIn('patch_image(', (ROOT/'build_mini_compat.py').read_text())
        self.assertNotIn('patch_image(', (ROOT/'build_dual.py').read_text())

    def test_exact_22_capabilities(self):
        expected={'atmega328p','atmega328','atmega328pb','atmega324a',
                  'atmega324p','atmega324pa','atmega324pb','atmega168',
                  'atmega168p','atmega168pb','atmega164a','atmega164p','atmega164pa',
                  'atmega8','atmega8a','atmega8515','atmega8535','atmega88','atmega88p',
                  'atmega16','atmega32a','atmega162'}
        self.assertEqual(set(build_mini.SPM512_COMPATIBLE),expected)
        for mcu,profile in build_mini.DEVICES.items():
            inc=(ROOT/'devices'/f'{mcu}.inc').read_text()
            self.assertIn(f'#define MINI_SPM512_CAPABLE {int(mcu in expected)}',inc)
            self.assertIn('#define SIG0 0x',inc)
            self.assertIn('#define SIG1 0x',inc)
            self.assertIn('#define SIG2 0x',inc)
            self.assertEqual(len(re.findall(r'^#define SIG[012] ',inc,re.M)),3)
            self.assertEqual(build_mini.supports_spm512(profile),mcu in expected)

    def test_peripheral_traits_not_uart_implicit(self):
        for chip,erase,ccp in [('attiny841',64,1),('attiny1634',128,2),
                               ('attiny84',64,0),('atmega328p',128,0)]:
            inc=(ROOT/'devices'/f'{chip}.inc').read_text()
            self.assertIn(f'#define MINI_FLASH_ERASE_GROUP_BYTES {erase}',inc)
            self.assertIn(f'#define MINI_WDT_CCP_STYLE {ccp}',inc)
        asm=(ROOT/'optiboot_mini.S').read_text()
        self.assertIn('#if MINI_FLASH_ERASE_GROUP_BYTES > FLASH_PAGE_BYTES',asm)
        self.assertIn('#elif MINI_WDT_CCP_STYLE',asm)
        self.assertIn('#if MINI_WIDE_BRANCHES',asm)

    def test_all_signatures_are_selected_one_at_a_time(self):
        import build_mini_compat
        with tempfile.TemporaryDirectory(prefix='unified-firmware-') as tmp:
            for chip in ('atmega328p','atmega168p','atmega16','atmega2560','attiny85'):
                args=type('Args',(),dict(output_dir=tmp,baud='auto',clock_source=None,
                    f_cpu=None,allow_overclock=False,allow_baud_error=False,signature_source='constants'))()
                command,path,compact=build_mini_compat.build_command(chip,args)
                r=subprocess.run(command,capture_output=True,text=True)
                self.assertEqual(r.returncode,0,f'{chip}: {r.stderr}')
                data=(path/f'{chip}.bin').read_bytes()
                meta=json.loads((path/f'{chip}.json').read_text())
                footer=meta['footer_bytes']
                self.assertIn(footer,(5,12))
                self.assertEqual(data[-footer:-footer+3],bytes(build_mini.DEVICES[chip]['sig']))
                self.assertEqual(meta['source_build_method'],'compile_target_profile')
                self.assertEqual(meta['boot_bytes'],512 if compact else 1024)

if __name__=='__main__':unittest.main()
