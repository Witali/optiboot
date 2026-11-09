"""Flash256 executable-opcode simulator tests. Not a physical AVR or real avrdude test."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(HERE)]
import build_flash256
from test_legacy_uart import LegacyAVR, symaddr
from test_modern_audit import AVRModern

OUTPUT=ROOT/'output'/'flash256'


class Legacy256(LegacyAVR):
    def __init__(self,img,dev,mcusr=2):
        super().__init__(b'\xff'*256+img,dev['flash'],tuple(dev['sig']),mcusr)
        self.boot_start=dev['flash']-256
        self.flash_size=dev['flash']
        self.flash=bytearray(b'\xff'*self.boot_start+img)
        self.pc=self.boot_start
        self.page_size=dev['page']
        self.page_buf={}
    def spm(self):
        cmd=self.io.get(0x57,0)
        z=self.z(); p=z & ~(self.page_size-1)
        if cmd==1:
            self.page_buf[z&(self.page_size-1)]=self.reg[0]
            self.page_buf[(z+1)&(self.page_size-1)]=self.reg[1]
        elif cmd==3:
            assert p<self.boot_start,(hex(p),hex(self.boot_start))
            self.flash[p:p+self.page_size]=b'\xff'*self.page_size
            self.erase_count+=1
        elif cmd==5:
            assert p<self.boot_start
            assert len(self.page_buf)==self.page_size,(len(self.page_buf),self.page_size)
            for offs,val in self.page_buf.items():self.flash[p+offs]=val
            self.page_buf={};self.write_count+=1
        elif cmd==0x11:pass
        else:raise AssertionError(f'Invalid SPM code {cmd:x}')
        self.io[0x57]=0


def make_cpu(mcu, mcusr=2):
    dev=build_flash256.build_mini.DEVICES[mcu]
    img=(OUTPUT/mcu/(mcu+'.bin')).read_bytes()
    obj=OUTPUT/mcu/(mcu+'.o')
    if dev['profile']=='legacy':
        c=Legacy256(img,dev,mcusr)
    else:
        c=AVRModern(img,dev['flash'],dev['page'],dev['eeprom'],mcusr)
    c.rxwait_pc=c.boot_start+symaddr(obj,'rx_wait')
    c.error_pc=c.boot_start+symaddr(obj,'bad_packet')
    c.wait_ready()
    return c,img,dev


def addr_command(byte_addr):
    assert byte_addr%2==0
    w=byte_addr//2
    return bytes((0x55,w&255,(w>>8)&255,0x20))


def write_command(payload, low_length_override=None):
    return bytes((0x64,0,len(payload) if low_length_override is None else low_length_override,ord('F')))+payload+b' '

class Flash256Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        subprocess.run([sys.executable,str(ROOT/'build_flash256.py'),'--all'],check=True,capture_output=True,text=True)

    def test_all_13_sizes_bootstart_and_opcode_safety(self):
        self.assertEqual(len(build_flash256.TARGETS),13)
        for mcu in build_flash256.TARGETS:
            with self.subTest(mcu=mcu):
                c,img,dev=make_cpu(mcu)
                self.assertEqual(len(img),256)
                self.assertLessEqual(len(img.rstrip(b'\xff')),256)
                self.assertEqual(c.boot_start,dev['flash']-256)
                self.assertEqual(c.flash[c.boot_start:],img)
                self.assertEqual(c.send(b'0 '),b'\x14\x10')
                self.assertEqual(c.send(b'A\x81 '),b'\x14\x03\x10')
                self.assertEqual(c.send(bytes((0x42,))+bytes(range(20))+b' '),b'\x14\x10')
                self.assertEqual(c.send(bytes((0x45,))+bytes(range(5))+b' '),b'\x14\x10')
                self.assertEqual(c.send(b'P '),b'\x14\x10')
                self.assertEqual(c.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                self.assertEqual(c.send(addr_command(0)),b'\x14\x10')
                payload=bytes(((i*17+13)&255) for i in range(dev['page']))
                self.assertEqual(c.send(write_command(payload)),b'\x14\x10')
                self.assertEqual(bytes(c.flash[:dev['page']]),payload)
                self.assertEqual(c.erase_count,1)
                self.assertEqual(c.write_count,1)
                last=c.boot_start-dev['page']
                self.assertEqual(c.send(addr_command(last)),b'\x14\x10')
                payload2=bytes(((i*27+21)&255) for i in range(dev['page']))
                self.assertEqual(c.send(write_command(payload2)),b'\x14\x10')
                self.assertEqual(bytes(c.flash[last:last+dev['page']]),payload2)
                self.assertEqual(c.erase_count,2)
                self.assertEqual(c.write_count,2)
                self.assertEqual(bytes(c.flash[c.boot_start:]),img)
                self.assertEqual(c.send(b'Q '),b'\x14\x10')

    def test_reset_on_watchdog_to_application(self):
        for mcu in build_flash256.TARGETS:
            with self.subTest(mcu=mcu):
                dev=build_flash256.build_mini.DEVICES[mcu]
                img=(OUTPUT/mcu/(mcu+'.bin')).read_bytes()
                if dev['profile']=='legacy':
                    c=Legacy256(img,dev,8)
                else:
                    c=AVRModern(img,dev['flash'],dev['page'],dev['eeprom'],8)
                for _ in range(100):
                    c.step()
                    if c.app_started:break
                self.assertTrue(c.app_started,(mcu,hex(c.pc)))
                reg=0x41 if dev['profile']=='legacy' else 0x60
                self.assertEqual(c.io.get(reg),0)

    def test_malformed_eop_preserves_last_app_page(self):
        for mcu in build_flash256.TARGETS:
            with self.subTest(mcu=mcu):
                c,img,dev=make_cpu(mcu)
                last=c.boot_start-dev['page']
                pattern=bytes((i*3+7)&255 for i in range(dev['page']))
                c.flash[last:c.boot_start]=pattern
                c.send(addr_command(last))
                c.rx.extend(write_command(bytes([0x11]*dev['page']))[:-1]+b'!')
                for _ in range(5000):
                    if c.pc==c.error_pc:break
                    c.step()
                else: self.fail(f'{mcu}: Bad EOP did not reach error loop')
                self.assertEqual(bytes(c.flash[last:c.boot_start]),pattern)
                self.assertEqual(c.erase_count,0)
                self.assertEqual(c.write_count,0)
                self.assertEqual(bytes(c.flash[c.boot_start:]),img)

    def test_boot_and_alignment_guards(self):
        for mcu in build_flash256.TARGETS:
            for offset in (0,2):
                with self.subTest(mcu=mcu,offset=offset):
                    c,img,dev=make_cpu(mcu)
                    c.send(addr_command(c.boot_start+offset if offset==0 else 2))
                    c.rx.extend(write_command(bytes([0x44]*dev['page'])))
                    for _ in range(1200):
                        if c.pc==c.error_pc:break
                        c.step()
                    else:self.fail(f'{mcu} did not reject unsafe address')
                    self.assertEqual(c.erase_count,0)
                    self.assertEqual(bytes(c.flash[c.boot_start:]),img)

    def test_hex_utility_and_page_packets(self):
        from flash256.upload_flash256 import make_pages, packet_for_page
        import build_mini
        from build_flash256 import TARGETS
        for mcu in TARGETS:
            page=build_mini.DEVICES[mcu]['page']
            content=bytes((4,0,0,0,0x11,0x22,0x33,0x44))
            line=':'+content.hex().upper()+f'{(-sum(content))&255:02X}'
            pages=make_pages(line+'\n:00000001FF\n',mcu)
            self.assertEqual(len(pages),1)
            addr,payload=pages[0]
            self.assertEqual(addr,0)
            self.assertEqual(payload[:4],b'\x11\x22\x33\x44')
            self.assertEqual(len(payload),page)
            la,write=packet_for_page(addr,payload)
            self.assertEqual(la,bytes((0x55,0,0,0x20)))
            self.assertEqual(write[:4],bytes((0x64,0,page,0x46)))
        with self.assertRaises(ValueError):
            make_pages(':01000000FF01\n:00000001FF\n','atmega8')

    def test_short_payload_never_erases(self):
        for mcu in build_flash256.TARGETS:
            with self.subTest(mcu=mcu):
                c,img,dev=make_cpu(mcu)
                c.send(addr_command(0))
                payload=bytes(range(dev['page']-2))
                c.rx.extend(bytes((0x64,0,len(payload),ord('F')))+payload+b' ')
                # Insufficient page data stalls in the receive loop, not SPM.
                for _ in range(1800):
                    if not c.rx and c.pc==c.rxwait_pc:break
                    c.step()
                self.assertEqual(c.erase_count,0)
                self.assertEqual(c.write_count,0)
                self.assertEqual(bytes(c.flash[c.boot_start:]),img)

if __name__=='__main__':unittest.main()
