"""Instruction-level AVR Flash256-readback tests (no physical AVRDUDE/silicon)."""
from pathlib import Path
import sys,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'mini_tests')]
import build_flash256_readback as builder
from test_flash256 import Legacy256,addr_command,write_command
from test_legacy_uart import LegacyAVR,symaddr
from test_modern_audit import AVRModern

class LegacyRead(Legacy256):
    def __init__(self,img,dev,mcusr=2):
        LegacyAVR.__init__(self,img,dev['flash'],tuple(dev['sig']),mcusr)
        self.boot_start=dev['flash']-len(img)
        self.flash_size=dev['flash']
        self.flash=bytearray(b'\xff'*self.boot_start+img)
        self.pc=self.boot_start
        self.page_size=dev['page'];self.page_buf={}

def reader(mcu,output,mcusr=2):
    dev=builder.build_mini.DEVICES[mcu]
    img=(output/mcu/(mcu+'.bin')).read_bytes()
    obj=output/mcu/(mcu+'.o')
    if dev['profile']=='legacy':
        c=LegacyRead(img,dev,mcusr)
    else:
        c=AVRModern(img,dev['flash'],dev['page'],dev['eeprom'],mcusr)
    c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
    c.error_pc=c.boot_start+symaddr(obj,'bad_packet')
    c.wait_ready()
    return c,img,dev

def read_command(n,mem=ord('F'), length_hi=0):
    return bytes((0x74,length_hi,n&255,mem,0x20))

class Flash256ReadbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        cls.dir=Path(cls.tmp.name)
        for mcu in builder.TARGETS:
            builder.one(mcu,cls.dir/mcu)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_all_13_boot_and_protocol(self):
        for mcu in builder.TARGETS:
            with self.subTest(mcu=mcu):
                c,img,dev=reader(mcu,self.dir)
                self.assertEqual(len(img),512)
                self.assertEqual(c.boot_start,dev['flash']-512)
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                for i in (0x81,0x82):
                    self.assertEqual(c.send(bytes((0x41,i,0x20))),b'\x14\x03\x10')
                self.assertEqual(c.send(b'B'+bytes(20)+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'E'+bytes(5)+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'P '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                self.assertEqual(c.send(b'Q '),b'\x14\x10')

    def test_watchdog_exit_and_flash256_original_unchanged(self):
        from test_flash256 import Legacy256
        for mcu in builder.TARGETS:
            with self.subTest(mcu=mcu):
                c, img, dev = reader(mcu, self.dir, mcusr=2)
                self.assertEqual(c.send(b'Q '), b'\x14\x10')
                # New instance starts at Boot with a watchdog reset flag set.
                if dev['profile']=='legacy':
                    c2=LegacyRead(img,dev,8)
                else:
                    c2=AVRModern(img,dev['flash'],dev['page'],dev['eeprom'],8)
                for _ in range(200):
                    if c2.app_started:break
                    c2.step()
                self.assertTrue(c2.app_started, mcu)
        original=Path('/mnt/data/optiboot_flash256_avrdude/output/flash256')
        current=ROOT/'output'/'flash256_unchanged'
        if original.exists() and current.exists():
            for mcu in builder.TARGETS:
                with self.subTest(original256=mcu):
                    self.assertEqual((original/mcu/(mcu+'.bin')).read_bytes(),
                                     (current/mcu/(mcu+'.bin')).read_bytes())

    def test_write_read_and_partial_read(self):
        for mcu in builder.TARGETS:
            with self.subTest(mcu=mcu):
                c,img,dev=reader(mcu,self.dir)
                for page in (0,c.boot_start-dev['page']):
                    data=bytes((0x23+page//dev['page']+i*29)&0xff for i in range(dev['page']))
                    self.assertEqual(c.send(addr_command(page)),b'\x14\x10')
                    self.assertEqual(c.send(write_command(data)),b'\x14\x10')
                    self.assertEqual(bytes(c.flash[page:page+dev['page']]),data)
                    self.assertEqual(c.send(addr_command(page)),b'\x14\x10')
                    self.assertEqual(c.send(read_command(dev['page'])),b'\x14'+data+b'\x10')
                    for count in (1,3,dev['page']-1):
                        self.assertEqual(c.send(addr_command(page)),b'\x14\x10')
                        self.assertEqual(c.send(read_command(count)),b'\x14'+data[:count]+b'\x10')
                self.assertEqual(c.erase_count,2);self.assertEqual(c.write_count,2)
                self.assertEqual(bytes(c.flash[c.boot_start:]),img)

    def test_reject_bad_lengths_type_and_boot_before_spm(self):
        for mcu in builder.TARGETS:
            dev=builder.build_mini.DEVICES[mcu]
            page=dev['page']
            for packet in (read_command(0),read_command(page+1),read_command(page,length_hi=1),read_command(page,mem=ord('E')),
                           write_command(bytes([0x55]*page),low_length_override=page-1)):
                with self.subTest(mcu=mcu,packet=packet[:5].hex()):
                    c,img,_=reader(mcu,self.dir)
                    self.assertEqual(c.send(addr_command(0)),b'\x14\x10')
                    c.rx.extend(packet)
                    for _ in range(5000):
                        if c.pc==c.error_pc:break
                        c.step()
                    else:self.fail(f'{mcu}: malformed request did not reach error loop')
                    self.assertEqual(c.erase_count,0)
                    self.assertEqual(bytes(c.flash[c.boot_start:]),img)
            for operation in ('read','write'):
                with self.subTest(mcu=mcu,op=operation):
                    c,img,_=reader(mcu,self.dir)
                    self.assertEqual(c.send(addr_command(c.boot_start)),b'\x14\x10')
                    packet=read_command(page) if operation=='read' else write_command(bytes([0x55]*page))
                    c.rx.extend(packet)
                    for _ in range(5000):
                        if c.pc==c.error_pc:break
                        c.step()
                    else:self.fail(f'{mcu}: boot access did not reach error loop')
                    self.assertEqual(c.erase_count,0);self.assertEqual(bytes(c.flash[c.boot_start:]),img)

    def test_error_eop_never_erases_last_app_page(self):
        for mcu in builder.TARGETS:
            with self.subTest(mcu=mcu):
                c,img,dev=reader(mcu,self.dir)
                addr=c.boot_start-dev['page']
                c.flash[addr:c.boot_start]=bytes([0xA5]*dev['page'])
                c.send(addr_command(addr))
                c.rx.extend(write_command(bytes([0x12]*dev['page']))[:-1]+b'!')
                for _ in range(10000):
                    if c.pc==c.error_pc:break
                    c.step()
                else:self.fail('Invalid EOP was not rejected')
                self.assertEqual(bytes(c.flash[addr:c.boot_start]),bytes([0xa5]*dev['page']))
                self.assertEqual(c.erase_count,0)

if __name__=='__main__':unittest.main()
