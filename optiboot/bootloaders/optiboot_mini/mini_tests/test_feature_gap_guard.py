"""Fail closed on Optiboot options that Mini would otherwise silently ignore."""
from pathlib import Path
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]

class MakeFeatureContract(unittest.TestCase):
    def test_explicit_led_option_fails_instead_of_disappearing(self):
        p=subprocess.run(['make','-f','Makefile.mini.inc','-n','mini','LED_START_FLASHES=3'],
                         cwd=ROOT,capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('LED_START_FLASHES',p.stderr)
        self.assertIn('does not implement',p.stderr)

    def test_explicit_app_spm_and_uart_selection_rejected(self):
        for setting in ('UART=1','RS485=B1','WDTTIME=2','APP_NOSPM=0','CUSTOM_VERSION=100'):
            with self.subTest(option=setting):
                p=subprocess.run(['make','-f','Makefile.mini.inc','-n','mini',setting],
                                 cwd=ROOT,capture_output=True,text=True)
                self.assertNotEqual(p.returncode,0)
                self.assertIn('does not implement',p.stderr)

    def test_normal_mini_make_target_stays_available(self):
        p=subprocess.run(['make','-f','Makefile.mini.inc','-n','mini'],
                         cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('build_mini.py',p.stdout)

if __name__=='__main__':unittest.main()
