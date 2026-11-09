"""R8 SPM executor sharing. Source-level and opcode-level regression.

The 512-byte boot image deliberately has GET_SIGN_ON disabled; synthetic
1024-byte boot simulation of GET_SIGN_ON is a test only, NOT flashable.
"""
from pathlib import Path
import json, subprocess, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
from test_modern_audit import AVRModern
from test_mega64_audit import AVR64
from test_legacy_uart import symaddr
from test_all_mcusr_spm_parity import with_mcusr
import build_mini
REF=HERE/'fixtures'/'r8_reference'

class R8SharedSPM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.out=Path(cls.tmp.name)
        cls.images={}
        for chip in ('atmega328p','atmega644p','atmega64a'):
            dst=cls.out/chip
            cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu',chip,'--f-cpu','16000000','--baud','115200','--output-dir',str(dst)]
            if chip=='atmega328p':cmd.insert(-2,'--app-spm-512')
            elif chip=='atmega644p':cmd.insert(-2,'--compact-644')
            elif chip=='atmega64a':cmd.insert(-2,'--compact-64k')
            p=subprocess.run(cmd,capture_output=True,text=True)
            if p.returncode: raise AssertionError(p.stderr)
            dev=build_mini.DEVICES[chip]
            data=(dst/(chip+'.bin')).read_bytes()
            cls.images[chip]=(dev,data,dst/(chip+'.o'),json.loads((dst/(chip+'.json')).read_text()))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def cpu(self, chip, baseline=False):
        dev,data,obj,meta=self.images[chip]
        if baseline:
            data=(REF/(chip+'.bin')).read_bytes()
            obj=REF/(chip+'.o')
        c=AVR64(data) if chip=='atmega64a' else AVRModern(data,dev['flash'],dev['page'],dev['eeprom'])
        c=with_mcusr(c,dev)
        c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
        c.error_pc=c.boot_start+symaddr(obj,'error_loop')
        c.wait_ready()
        return c

    def test_sizes_reduce_without_footprint_growth(self):
        self.assertEqual(self.images['atmega328p'][3]['code_bytes'],498)
        self.assertEqual(self.images['atmega644p'][3]['code_bytes'],492)
        self.assertEqual(self.images['atmega64a'][3]['code_bytes'],498)
        for chip in self.images:
            dev,data,_,meta=self.images[chip]
            old=json.loads((REF/(chip+'.json')).read_text())
            self.assertLess(meta['code_bytes'],old['code_bytes'])
            self.assertEqual(meta['boot_bytes'],old['boot_bytes'])
            self.assertEqual(data[-5:],bytes(dev['sig'])+b'\x03\x08')

    @unittest.skipUnless(all((REF/(chip+ext)).is_file() for chip in ('atmega328p','atmega644p','atmega64a') for ext in ('.bin','.o')), 'Historical comparison requires snapshots omitted from the 2026-11-08 archive')
    def test_r7_r8_protocol_and_memory_equal(self):
        for chip in self.images:
            dev,image,_,meta=self.images[chip]
            a=self.cpu(chip,baseline=True)
            b=self.cpu(chip)
            for packet in (b'0 ',b'1 ',b'A\x81 ',b'A\x82 ',b'u ',b'B'+bytes(20)+b' ',b'E'+bytes(5)+b' '):
                with self.subTest(chip=chip, packet=packet):
                    self.assertEqual(a.send(packet),b.send(packet))
            for i in range(3):
                packet=bytes((0x56,0x30,0,i,0,0x20))
                self.assertEqual(a.send(packet),b.send(packet))
            for address in (0,0x200,a.boot_start-dev['page']):
                data=bytes((i*7+(address//dev['page']))&255 for i in range(dev['page']))
                load=bytes((0x55,(address>>1)&255,(address>>9)&255,0x20))
                write=bytes((0x64,dev['page']>>8,dev['page']&255,ord('F')))+data+b' '
                read=bytes((0x74,dev['page']>>8,dev['page']&255,ord('F'),0x20))
                for q in (load,write,load,read):
                    self.assertEqual(a.send(q),b.send(q),(chip,address,len(q)))
                self.assertEqual(bytes(a.flash[:a.boot_start]),bytes(b.flash[:b.boot_start]))
            for address in (0,dev['eeprom']-16):
                payload=bytes((i*17+3)&255 for i in range(16))
                load=bytes((0x55,(address>>1)&255,(address>>9)&255,0x20))
                for q in (load,b'd\x00\x10E'+payload+b' ',load,b't\x00\x10E '):
                    self.assertEqual(a.send(q),b.send(q),(chip,address))
                self.assertEqual(bytes(a.eeprom),bytes(b.eeprom))
            self.assertEqual(bytes(b.flash[b.boot_start:]),image)

    def test_512_getsignon_rejected_still(self):
        out=self.out/'too_large'
        cmd=[sys.executable,str(ROOT/'build_mini.py'),'--mcu','atmega328p','--app-spm-512',
             '--compact-sign-on','--f-cpu','16000000','--baud','115200','--output-dir',str(out)]
        p=subprocess.run(cmd,capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('520 bytes exceed 512 bytes',p.stderr)

if __name__=='__main__':unittest.main()
