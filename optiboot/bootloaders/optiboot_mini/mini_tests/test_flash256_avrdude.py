"""Host-command trace following avrdude/src/stk500.c and src/arduino.c (2026-10-31).

This emulates the requests and exercises assembled AVR opcodes; it does NOT
execute the AVRDUDE executable, a USB-UART, or a physical AVR device.
"""
from pathlib import Path
import sys, unittest, subprocess
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'mini_tests')]
import build_flash256
from test_flash256 import make_cpu, addr_command, write_command
from flash256.prepare_avrdude_hex import prepare
from flash256.upload_flash256 import parse_intel_hex

OUT=ROOT/'output'/'flash256'

class AvrdudeFlash256Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable,str(ROOT/'build_flash256.py'),'--all'],check=True,capture_output=True,text=True)

    def test_arduino_stk500_v1_command_trace(self):
        # Actual stk500.c init: GET_PARAMETER twice, SET_DEVICE (20),
        # SET_DEVICE_EXT (4/5, here 5 since GET_PARAMETER returns 3),
        # ENTER_PROGMODE, signature from arduino.c READ_SIGN, page writes,
        # LOAD_ADDRESS per page and LEAVE_PROGMODE.
        for mcu in build_flash256.TARGETS:
            with self.subTest(mcu=mcu):
                cpu, original, dev=make_cpu(mcu)
                self.assertEqual(cpu.send(b'0 '),b'\x14\x10')
                for sw in (0x81,0x82):
                    self.assertEqual(cpu.send(bytes([0x41,sw,0x20])),b'\x14\x03\x10')
                params=bytes((i*3+7)&255 for i in range(20))
                self.assertEqual(cpu.send(b'B'+params+b' '),b'\x14\x10')
                self.assertEqual(cpu.send(b'E'+bytes([4,0,0xD7,0xA0,0])+b' '),b'\x14\x10')
                self.assertEqual(cpu.send(b'P '),b'\x14\x10')
                self.assertEqual(cpu.send(b'u '),b'\x14'+bytes(dev['sig'])+b'\x10')
                last=cpu.boot_start-dev['page']
                for addr in (0,last):
                    pattern=bytes((i*13+0x25+addr//dev['page'])&255 for i in range(dev['page']))
                    self.assertEqual(cpu.send(addr_command(addr)),b'\x14\x10')
                    self.assertEqual(cpu.send(write_command(pattern)),b'\x14\x10')
                    self.assertEqual(bytes(cpu.flash[addr:addr+dev['page']]),pattern)
                self.assertEqual(cpu.send(b'Q '),b'\x14\x10')
                self.assertEqual(bytes(cpu.flash[cpu.boot_start:]),original)
                self.assertEqual(cpu.erase_count,2)
                self.assertEqual(cpu.write_count,2)

    def test_unaligned_last_block_padded_by_preprocessor(self):
        # Unpadded HEX ends at 0x0023; avrdude would send 36 bytes,
        # whereas the minimal loader consumes 64/128. Check preparer
        # extends it to full page and embedded bytes remain unchanged.
        for mcu in build_flash256.TARGETS:
            with self.subTest(mcu=mcu):
                original={0:0x33,1:0x44,0x20:0x55,0x23:0x66}
                lines=[]
                for a,b in original.items():
                    fields=bytes([1,a>>8,a&255,0,b]); lines.append(':'+fields.hex().upper()+f'{(-sum(fields))&255:02X}')
                lines.append(':00000001FF')
                converted,n,end=prepare('\n'.join(lines)+'\n',mcu)
                parsed=parse_intel_hex(converted)
                page=build_flash256.build_mini.DEVICES[mcu]['page']
                self.assertEqual(end,page-1)
                self.assertEqual(n,1)
                self.assertEqual(len(parsed),page)
                for a,b in original.items():self.assertEqual(parsed[a],b)
                for a,b in parsed.items():
                    if a not in original:self.assertEqual(b,0xff)
                cpu,img,dev=make_cpu(mcu)
                self.assertEqual(cpu.send(addr_command(0)),b'\x14\x10')
                frame=bytes(parsed[i] for i in range(page))
                self.assertEqual(cpu.send(write_command(frame)),b'\x14\x10')
                self.assertEqual(bytes(cpu.flash[:page]),frame)

    def test_boot_overlap_rejected_before_adding_padding(self):
        for mcu in build_flash256.TARGETS:
            dev=build_flash256.build_mini.DEVICES[mcu]
            bad=dev['flash']-256
            line=bytes([1,bad>>8,bad&255,0,0x5a])
            h=':'+line.hex().upper()+f'{(-sum(line))&255:02X}'+'\n:00000001FF\n'
            with self.assertRaises(ValueError):prepare(h,mcu)

    def test_nonmatching_exotic_packets_not_part_of_arduino_contract(self):
        # Document scope, do not treat -c stk500v1 as equivalent to -c arduino
        # (the former may require STK_UNIVERSAL for signature).
        self.assertFalse('STK_UNIVERSAL' in build_flash256.one('atmega8', ROOT/'output'/'_flash256_contract_probe')['supported'])
        self.assertFalse('STK_READ_PAGE' in build_flash256.one('atmega8', ROOT/'output'/'_flash256_contract_probe')['supported'])

if __name__=='__main__':unittest.main()
