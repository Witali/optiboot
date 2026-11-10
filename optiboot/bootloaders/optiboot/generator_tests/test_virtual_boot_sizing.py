"""Canonical CLI, image identity, shared geometry, and tiny-host agreement."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tiny'),str(ROOT/'mini_tests')]
import generate_firmware as generator
import device_database as database
from patch_vectors import patch_application,rjmp,validate_boot_size
from make_seed import make_seed
from flash_tiny import Stk500Mini,upload
from test_tiny_host import Loopback


class VirtualBootGeneratorTests(unittest.TestCase):
    def test_all_middle_images_match_imported_reference_and_host_tools(self):
        reference=json.loads((ROOT/'mini_tests/fixtures/virtual_boot_2026-11-08_sha256.json').read_text())
        clocks={'attiny84':8_000_000,'attiny85':8_000_000,'attiny841':16_000_000,'attiny1634':12_000_000}
        with tempfile.TemporaryDirectory() as tmp:
            for chip,hz in clocks.items():
                with self.subTest(mcu=chip):
                    info=generator.build_one(chip,'middle',hz,out=Path(tmp))
                    dev=database.DEVICES[chip]
                    size=576 if chip in ('attiny84','attiny85') else 512
                    start=dev['flash']-size
                    self.assertEqual(info['boot_bytes'],size)
                    self.assertEqual(int(info['boot_start'],16),start)
                    blob=Path(info['files']['bin']).read_bytes()
                    self.assertEqual(hashlib.sha256(blob).hexdigest(),reference[chip])
                    self.assertEqual(info['flash_erase_group_bytes'],dev['flash_erase_group_bytes'])
                    self.assertEqual(info['virtual_boot_sizing_policy'],'smallest_whole_erase_groups_at_least_512B')
                    reset=rjmp(0,0x100//2,dev['flash']//2)
                    app={0:reset&255,1:reset>>8,start-1:0x37}
                    patched,details=patch_application(app,chip,boot_bytes=size)
                    self.assertEqual(details['boot_bytes'],size)
                    self.assertEqual(len(make_seed(blob,chip,boot_bytes=size)),size+4)
                    port=Loopback()
                    upload(Stk500Mini(port),patched,chip,boot_bytes=size)
                    self.assertEqual(port.mem[start-1],0x37)
                    # An older installation's default must reject the new reset.
                    with self.assertRaisesRegex(ValueError,'reserved|region|patched'):
                        upload(Stk500Mini(Loopback()),patched,chip)
                    with self.assertRaisesRegex(ValueError,'Expected boot image'):
                        make_seed(blob,chip)

    def test_invalid_geometry_and_sizes_fail_before_upload(self):
        for chip in ('attiny84','attiny85','attiny841','attiny1634'):
            for size in (0,256,513,1025,False,576.5):
                with self.subTest(mcu=chip,size=size),self.assertRaises(ValueError):
                    validate_boot_size(chip,size)
        with self.assertRaises(ValueError):
            database.virtual_boot_sizes(database.DEVICES['atmega328p'])

    def test_root_launcher_preserves_canonical_selection_and_dry_run(self):
        launcher=ROOT.parents[2]/'generate_firmware.py'
        for argv in (['--list'],['attiny85','middle','8MHz','--dry-run'],
                     ['atmega168pb','mini','16MHz','--dry-run']):
            with self.subTest(args=argv):
                root=subprocess.run([sys.executable,str(launcher),*argv],capture_output=True,text=True)
                canonical=subprocess.run([sys.executable,str(ROOT/'generate_firmware.py'),*argv],capture_output=True,text=True)
                self.assertEqual(root.returncode,0,root.stderr)
                self.assertEqual(root.stdout,canonical.stdout)


if __name__=='__main__':unittest.main()
