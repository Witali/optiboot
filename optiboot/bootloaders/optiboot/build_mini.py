#!/usr/bin/env python3
"""Build the Optiboot Mini multi-device AVR assembly (all output is English)."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import device_database
from device_database import DEVICES

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'optiboot_mini.S'  # The only active firmware assembly source.


def assembler_target(mcu, compiler):
    """Use the same ISA with our exact device map when old GCC lacks 324PB specs."""
    if mcu == 'atmega324pb' and Path(compiler).name.startswith('avr-gcc'):
        spec = subprocess.check_output([compiler,
            '-print-file-name=device-specs/specs-atmega324pb'], text=True).strip()
        if not Path(spec).is_file():
            return 'atmega324pa', ['-U__AVR_ATmega324PA__', '-D__AVR_ATmega324PB__=1']
    return mcu, []


def linked_object(obj: Path, mcu: str) -> Path:
    """Resolve local AVR relocations without changing offsets or relaxing code."""
    if not shutil.which('readelf'):
        raise RuntimeError('Missing readelf: cannot verify AVR relocations')
    def relocations(path):
        return subprocess.check_output(['readelf', '-r', str(path)], text=True)
    if 'There are no relocations in this file' in relocations(obj):
        return obj
    if not shutil.which('avr-ld'):
        raise RuntimeError('Local AVR relocations require avr-ld; do not flash an unlinked object')
    dev = DEVICES[mcu]
    arch = device_database.linker_architecture(dev)
    linked = obj.with_suffix('.elf')
    try:
        subprocess.run(['avr-ld', '-m', arch, '-Ttext=0', '-e', '_start',
                        str(obj), '-o', str(linked)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError('AVR link failed: ' + (error.stderr or str(error))) from error
    if 'There are no relocations in this file' not in relocations(linked):
        raise RuntimeError('Linked image has unresolved relocations; do not flash it')
    return linked


def supports_spm512(dev: dict) -> bool:
    """Approved 8/16/32-KiB classical ATmega targets with 512-byte hardware Boot."""
    return bool(dev.get('spm512_capable'))

SPM512_COMPATIBLE = tuple(name for name, dev in DEVICES.items() if supports_spm512(dev))
COMPACT_644 = ('atmega644', 'atmega644a', 'atmega644p', 'atmega644pa')
COMPACT_64K = COMPACT_644 + ('atmega640',)
COMPACT_LEGACY64 = ('atmega64a',)
COMPACT_BANKED = ('atmega128a','atmega1280','atmega1281','atmega1284','atmega1284p','atmega2560','atmega2561')
BASELINE_SHA256 = '3d3b3ab48a72ee2439b531d2d079060a649626348eaba0d322f240eb82074c14'
SUPPORTED_CLOCKS = ('external_crystal', 'external_clock', 'internal_rc')
MIN_F_CPU = 8_000_000  # Project policy: no AVR bootloader builds below 8 MHz
MAX_F_CPU = 28_000_000


def best_baud(f_cpu, baud):
    choices=[]
    for multiplier, u2x in ((16,0),(8,1)):
        nominal=f_cpu/(multiplier*baud)-1
        for d in {int(math.floor(nominal)), int(math.ceil(nominal)),int(round(nominal))}:
            if 0<=d<=4095:
                actual=f_cpu/(multiplier*(d+1))
                error=100*(actual-baud)/baud
                choices.append((abs(error),u2x,d,actual,error))
    if not choices:
        raise ValueError('BAUD_RATE is out of the USART divider range')
    # For an equally good error, prefer normal speed, which has wider sampling margin.
    choices.sort(key=lambda x:(x[0],x[1]))
    _,u2x,divider,actual,error=choices[0]
    return {'u2x':u2x,'ubrr':divider,'actual_baud':actual,'baud_error_percent':error}


def make_hex(binary, base):
    """Intel HEX including extended linear addresses up to 256-KiB."""
    if base + len(binary) > 262144:
        raise ValueError('HEX image extends beyond 256 KiB')
    lines = []
    last_upper = 0
    for i in range(0,len(binary),16):
        data = binary[i:i+16]
        addr = base+i
        upper=addr>>16
        if upper != last_upper:
            ela=bytes((2,0,0,4,(upper>>8)&255,upper&255))
            lines.append(':'+ela.hex().upper()+format((-sum(ela))&255,'02X'))
            last_upper = upper
        record=bytes((len(data),(addr>>8)&255,addr&255,0))+data
        lines.append(':'+record.hex().upper()+format((-sum(record))&255,'02X'))
    return '\n'.join(lines+[':00000001FF',''])


def compiler_tools(selection):
    for name,cc,oc,flags in [
            ('clang','clang','llvm-objcopy',['-target','avr']),
            ('gcc','avr-gcc','avr-objcopy',[])]:
        if selection not in ('auto',name):continue
        if shutil.which(cc) and shutil.which(oc):
            return name,cc,oc,flags
    raise RuntimeError('Missing AVR toolchain: install clang+llvm-objcopy or avr-gcc+avr-objcopy')


def build(args):
    mcu=args.mcu.lower().strip()
    if mcu not in DEVICES:
        raise ValueError(f'Unsupported MCU {mcu!r}; use --list-chips')
    dev=DEVICES[mcu]
    device_database.check_generated_device(mcu)
    if args.legacy_eeprom_byte_address and mcu not in ('atmega64a','atmega128a'):
        raise ValueError('Old AVRDUDE EEPROM byte addressing is only supported for ATmega64A/ATmega128A')
    f_cpu=int(args.f_cpu) if args.f_cpu is not None else int(os.environ.get('F_CPU', 8000000 if dev['profile'] in ('soft85','soft84') else 16000000))
    if not MIN_F_CPU <= f_cpu <= MAX_F_CPU:
        raise ValueError(f'F_CPU must be between {MIN_F_CPU} and {MAX_F_CPU} Hz; frequencies below 8 MHz are unsupported')
    clock_source=args.clock_source or os.environ.get('CLOCK_SOURCE', 'internal_rc' if dev['profile'] in ('soft85','soft84') else 'external_crystal')
    if clock_source=='internal_rc' and f_cpu != 8_000_000:
        raise ValueError('internal_rc builds use 8 MHz only; check oscillator calibration, CLKPR and CKDIV8 fuses')
    if f_cpu > dev['max_mhz']*1000000:
        if not args.allow_overclock:
            raise ValueError(f'{mcu}: rated maximum is {dev["max_mhz"]} MHz. Use --allow-overclock only for deliberate, unverified overclocking.')
        print(f'WARNING: {mcu} at {f_cpu/1e6:g} MHz exceeds rated {dev["max_mhz"]} MHz; clock/voltage/UART reliability NOT guaranteed.',file=sys.stderr)
    soft_serial = dev['profile'] in ('soft85','soft84')
    if args.baud == 'auto' and soft_serial:
        # 115200 at 16+ MHz is bit-timing-testable with an external clock.
        # At 8 MHz a 115200-bit period is only ~69 CPU cycles, below
        # the validated software UART implementation minimum of 100.
        # External 8 MHz defaults to 57600, while 8 MHz RC remains 19200.
        if clock_source == 'internal_rc':
            baud = 19200
        elif f_cpu >= 16_000_000:
            baud = 115200
        elif f_cpu >= 10_000_000:
            baud = 57600
        else:
            baud = 57600  # 8 MHz external, bit-level tested at +/-1.5% host drift
    elif args.baud == 'auto':
        if clock_source=='internal_rc':
            # conservative nominal defaults: RC error and temperature drift are additional
            baud=38400
        else:
            # At 8 MHz, 38400 (normal 16x oversampling) has +0.16% divider error;
            # 57600 gives +2.12% and 115200 is outside the default tolerance.
            baud=38400 if f_cpu == 8_000_000 else (115200 if abs(best_baud(f_cpu,115200)['baud_error_percent'])<=2.5 else 57600)
    else:
        baud=int(args.baud)
        if baud<=0:raise ValueError('BAUD_RATE must be positive')
    uart=best_baud(f_cpu,baud) if not soft_serial else {
        'u2x':0,'ubrr':0,'actual_baud':f_cpu/round(f_cpu/baud),
        'baud_error_percent':100*(f_cpu/round(f_cpu/baud)-baud)/baud}
    if soft_serial and not (100 <= round(f_cpu/baud) <= 750):
        raise ValueError('Software UART needs 100..750 CPU cycles per bit; choose another baud/clock')
    error_lim=1.5 if clock_source=='internal_rc' else 2.5
    if abs(uart['baud_error_percent'])>error_lim and not args.allow_baud_error:
        raise ValueError(f'UART error {uart["baud_error_percent"]:+.2f}% exceeds {error_lim:.1f}% limit; change baud or --allow-baud-error')
    if clock_source=='internal_rc':
        print('NOTICE: internal RC uses fuse/CLKPR settings made outside this bootloader; RC drift requires calibration and real UART testing.',file=sys.stderr)
    tcname,cc,oc,tcflags=compiler_tools(args.toolchain)
    output=Path(args.output_dir).resolve() if args.output_dir else (ROOT/'output'/'spm'/mcu if args.app_spm else ROOT/'output'/mcu)
    output.mkdir(parents=True,exist_ok=True)
    virtual = bool(dev.get('virtual_boot'))
    compact64 = args.compact_644 or args.compact_64k
    compactbanked = args.compact_banked
    compacttiny = args.compact_tiny
    if args.fuse_lock_read and not compact64:
        raise ValueError('--fuse-lock-read requires --compact-64k or --compact-644 (1024-byte physical Boot)')
    if compact64:
        allowed = COMPACT_644 if args.compact_644 else COMPACT_64K + COMPACT_LEGACY64
        if mcu not in allowed:
            raise ValueError('--compact-644 is only for ATmega644/644A/644P/644PA' if args.compact_644 else
                             '--compact-64k requires an audited 64KiB/256-byte-page ATmega UART profile')
        if str(args.boot_bytes) not in ('auto','1024'):
            raise ValueError('64KiB ATmega Boot fuses allow a minimum of 1024 bytes, never 512')
        args.boot_bytes = '1024'
        args.app_spm = True
        args.universal_signature = True
        args.compact_signature = True
    if compacttiny:
        if not virtual:
            raise ValueError('--compact-tiny requires an ATtiny with a Virtual Boot protocol')
        if args.app_spm or args.app_spm_512 or args.compact_64k or args.compact_644 or args.compact_banked:
            raise ValueError('--compact-tiny must not be combined with hardware-Boot profiles')
        if str(args.boot_bytes) != 'auto':
            device_database.validate_virtual_boot_size(dev, args.boot_bytes)
        args.universal_signature=True
        args.compact_signature=True
    if compactbanked:
        if mcu not in COMPACT_BANKED:
            raise ValueError('--compact-banked is only supported on 128/256-KiB ATmega with banked addressing')
        if args.compact_64k or args.compact_644 or args.app_spm_512:
            raise ValueError('--compact-banked must not be combined with other compact profile selectors')
        if str(args.boot_bytes) not in ('auto','1024'):
            raise ValueError('--compact-banked requires a 1024-byte physical Boot section')
        args.boot_bytes = '1024'
        args.app_spm=True
        args.universal_signature=True
        args.compact_signature=True
    if args.app_spm_512:
        if mcu not in SPM512_COMPATIBLE:
            raise ValueError('--app-spm-512 requires an audited 8/16/32KiB classic ATmega')
        if str(args.boot_bytes) not in ('auto','512'):
            raise ValueError('--app-spm-512 requires exactly 512 boot bytes')
        args.boot_bytes='512'
        args.app_spm=True
        args.universal_signature=True
        args.compact_signature=True
    if args.virtual_app_spm:
        raise ValueError('Virtual Boot ATtiny has direct application SPM; --virtual-app-spm is removed')
    if args.app_spm and virtual:
        raise ValueError('ATtiny applications execute SPM directly; no callable boot SPM ABI is needed')
    # Hardware BOOTSZ1:0 supports exactly four sizes (factor 2 each).
    # MAX is 2KiB on 8/16KiB AVRs, 4KiB on 32KiB AVRs, and
    # 8KiB on the supported 64/128/256KiB AVRs.  Flash//2 is NOT a valid
    # substitute: it silently allowed non-existent 4/8KiB fuse selections.
    max_boot = 2048 if dev['flash'] <= 16384 else (4096 if dev['flash'] <= 32768 else 8192)
    hardware_boot_sizes = [max_boot//8, max_boot//4, max_boot//2, max_boot]
    capacities = (list(device_database.virtual_boot_sizes(dev)) if compacttiny else
                  [dev['default_boot']] if virtual else
                  [b for b in hardware_boot_sizes if b >= dev['default_boot']])
    if args.app_spm and not args.app_spm_512:
        capacities=[size for size in capacities if size >= 1024]
        if not capacities:
            raise ValueError('--app-spm needs a hardware boot section of at least 1024 bytes')
    if args.boot_bytes != 'auto':
        size=int(args.boot_bytes)
        if size not in capacities:
            raise ValueError(f'BOOT_BYTES={size} not allowed for {mcu}; choices are {capacities}')
        capacities=[size]
    assembler_mcu, device_flags = assembler_target(mcu, cc)
    # GNU as cannot parse C integer suffixes in software-UART delay expressions.
    flags=[*tcflags, '-mmcu='+assembler_mcu, *device_flags, f'-DF_CPU={f_cpu}',f'-DBAUD_RATE={baud}', f'-DMINI_U2X={uart["u2x"]}',f'-DMINI_UBRR={uart["ubrr"]}', '-I',str(ROOT)]
    if args.legacy_eeprom_byte_address:
        flags.append('-DMINI_OLD_AVRDUDE_EEPROM=1')
    if getattr(args, "signature_source", "constants") == "auto":
        args.signature_source = "hardware" if dev.get("sigrow_lpm_supported_by_datasheet", False) else "constants"
    if args.signature_source == "hardware" and not dev.get("sigrow_lpm_supported_by_datasheet", False):
        raise ValueError(f"{mcu}: SIGRD+LPM has not been audited; use --signature-source constants")
    if args.signature_source == "hardware":
        flags.append("-DMINI_SIGROW_HARDWARE=1")
    if args.universal_signature:
        flags.append('-DMINI_UNIVERSAL_SIGNATURE=1')
    if args.app_spm:
        flags.append('-DMINI_APP_SPM=1')
    if args.mcusr_parity:
        flags.append('-DMINI_MCUSR_PARITY=1')
    if args.app_spm_512 or compact64 or compactbanked:
        flags.append('-DMINI_APP_SPM_512=1')
    if compactbanked:
        flags.append('-DMINI_COMPACT_BANKED=1')
    if compacttiny:
        flags.append('-DMINI_TINY_COMPACT=1')
    if compact64:
        flags.append('-DMINI_COMPACT_64K=1')
    if args.compact_sign_on:
        if not (args.app_spm_512 or compact64 or compactbanked or compacttiny):
            raise ValueError('--compact-sign-on is only for compact profile(s)')
        flags.append('-DMINI_COMPACT_SIGN_ON=1')
    if args.fuse_lock_read:
        flags.append('-DMINI_COMPACT_FUSE_LOCK_READ=1')
    if args.compact_signature:
        if not args.universal_signature:
            raise ValueError('--compact-signature requires --universal-signature')
        if mcu not in SPM512_COMPATIBLE and not compact64 and not compactbanked and not compacttiny:
            raise ValueError('Compact-signature requires a validated classic ATmega compact profile')
        if not compact64 and not compactbanked and not compacttiny and str(args.boot_bytes) not in ('auto','512'):
            raise ValueError('--compact-signature needs either 512-byte BOOTSZ or --compact-64k / --compact-644')
        if not args.fuse_lock_read:
            print('WARNING: Compact SPM STK_UNIVERSAL replies 0 to fuse/lock reads. '
                  'Do not use this variant to diagnose or change fuse/lock bytes.',file=sys.stderr)
        flags.append('-DMINI_COMPACT_UNIVERSAL_SIGNATURE=1')
    last_message=''
    for boot_bytes in capacities:
        obj=output/(mcu+'.o')
        image=output/(mcu+'.bin')
        cmd=[cc,*flags,f'-DBOOT_BYTES={boot_bytes}','-c',str(SOURCE),'-o',str(obj)]
        completed=subprocess.run(cmd,capture_output=True,text=True)
        if completed.returncode:
            last_message=completed.stderr.strip()
            if args.boot_bytes == 'auto':
                continue
            raise RuntimeError(last_message)
        image_obj = linked_object(obj, mcu)
        subprocess.run([oc,'-O','binary','-j','.text',str(image_obj),str(image)],check=True,capture_output=True)
        b=image.read_bytes()
        if len(b)>boot_bytes:
            last_message=f'{len(b)} bytes exceed {boot_bytes} bytes of boot space'
            continue
        if len(b)!=boot_bytes:
            last_message=f'Generated {len(b)} bytes instead of {boot_bytes} bytes'
            continue
        compact_abi = args.app_spm_512 or compact64 or compactbanked
        footer_sig = b'' if args.signature_source == 'hardware' else bytes(dev['sig'])
        footer=(footer_sig+bytes((3,8)) if (compact_abi or compacttiny) and not args.compact_sign_on
                else footer_sig+b'AVR STK'+bytes((3,8)))
        if b[-len(footer):]!=footer:
            raise RuntimeError(f'{mcu} boot footer does not match expected signature/version')
        base=dev['flash']-boot_bytes
        if compact_abi:
            # SPM service executes at BOOT_START+2 for both compact modes.
            expected_cpi=bytes((0x90 | ((base >> 8) & 0xF), 0x30 | ((base >> 12) & 0xF)))
            if compactbanked:
                sym_abi = subprocess.check_output(['llvm-objdump','-t',str(obj)],text=True)
                if not re.search(r'^00000002\s+g\s+\.text\s+\S+\s+optiboot_mini_do_spm$',sym_abi,re.M):
                    raise RuntimeError('Banked compact ABI entry is not at BOOT_START+2')
            elif (b[1] & 0xF0) != 0xC0 or b[2:4] != expected_cpi:
                raise RuntimeError('Compact SPM executable entry missing at BOOT_START+2')
        elif args.app_spm:
            # Full service has a 2-word jump table and a separate body.
            if (b[1] & 0xF0) != 0xC0 or (b[3] & 0xF0) != 0xC0 or b[4:6]!=bytes((0xF8,0x94)):
                raise RuntimeError('Unexpected SPM entry table at BOOT_START+2 or missing CLI')
        elif b[:2]!=bytes((0xF8,0x94)):
            raise RuntimeError('Unexpected boot entry, expected CLI opcode')
        if base % dev['page']:
            raise RuntimeError('Boot start is not page-aligned')
        sha=hashlib.sha256(b).hexdigest()
        if args.verify_baseline and sha!=BASELINE_SHA256:
            raise RuntimeError('The baseline 328P 16MHz 115200 image changed: '+sha)
        (output/(mcu+'.hex')).write_text(make_hex(b,base))
        # count machine-code bytes by the assembler's _code_end symbol
        sym=subprocess.check_output(['llvm-objdump','-t',str(obj)],text=True)
        m=re.search(r'^([0-9a-fA-F]{8,16})\s+g\s+\.text\s+\S+\s+_code_end$',sym,re.M)
        code_bytes=int(m.group(1),16) if m else None
        if code_bytes is not None and code_bytes+len(footer)>boot_bytes:
            raise RuntimeError('Code section overlaps footer')
        if compact64 and not args.fuse_lock_read and not args.compact_sign_on and code_bytes+len(footer)>512:
            raise RuntimeError('Compact 64KiB code+footer exceeds 512-byte code budget (physical Boot is 1024)')
        result={'mcu':mcu,'assembler_mcu':assembler_mcu,'flash_bytes':dev['flash'],'eeprom_bytes':dev['eeprom'],'flash_page_bytes':dev['page'],
            'f_cpu_hz':f_cpu,'clock_source':clock_source,'baud_requested':baud,**uart,'toolchain':tcname,
            'boot_bytes':boot_bytes,'boot_start_hex':f'0x{base:04X}','code_bytes':code_bytes,
            'boot_size_max_bytes':None if virtual else max_boot,
            'bootsz1_0_bits':None if virtual else f'{(hardware_boot_sizes.index(boot_bytes) ^ 3):02b}',
            'bootrst_programmed_required':not virtual,
            'virtual_boot_vector_patch_required':virtual,
            'selfprgen_fuse_programmed_required':virtual,
            'virtual_boot_flash_transfer_bytes':dev['flash_erase_group_bytes'] if virtual else None,
            'virtual_boot_erase_group_aligned':bool(virtual and boot_bytes % dev['flash_erase_group_bytes'] == 0),
            'virtual_boot_page_aligned':bool(virtual and boot_bytes % dev['page'] == 0),
            'virtual_boot_sizing_policy':('smallest_whole_erase_groups_at_least_512B' if compacttiny and args.boot_bytes == 'auto'
                                          else 'explicit_whole_erase_groups' if compacttiny
                                          else 'legacy_1024B' if virtual else None),
            'soft_uart':soft_serial, 'soft_uart_tx_pin':'PB0' if mcu=='attiny85' else 'PA1' if mcu=='attiny84' else None,
            'soft_uart_rx_pin':'PB1' if mcu=='attiny85' else 'PA2' if mcu=='attiny84' else None,
            'hardware_boot_fuse_supported':not virtual,
            'eeprom_host_addressing':'byte' if args.legacy_eeprom_byte_address else 'word',
            'stk_read_sign_0x75':True,
            'signature_source':args.signature_source,
            'sigrow_lpm_datasheet_supported':bool(dev.get('sigrow_lpm_supported_by_datasheet',False)),
            'stk_get_sign_on_string':bool(args.compact_sign_on or not (compact_abi or compacttiny)),
            'stk_set_parameter_2byte':not (compact_abi or compacttiny),
            'footer_bytes':len(footer), 'compact_sign_on':bool(args.compact_sign_on),
            'stk_universal_signature_0x30':bool(args.universal_signature),
            'stk_universal_fuse_lock_reads':not args.compact_signature or bool(args.fuse_lock_read),
            'app_spm':bool(args.app_spm),
            'app_spm_512':bool(args.app_spm_512),
            'compact_644':bool(args.compact_644), 'compact_64k':bool(compact64), 'compact_banked':bool(compactbanked), 'compact_tiny':bool(compacttiny),
            'compact_fuse_lock_read':bool(args.fuse_lock_read),
            'payload_under_512': bool(code_bytes+len(footer)<=512),
            'compact_payload_bytes':code_bytes+len(footer) if compact_abi or compacttiny else None,
            'mcusr_parity':bool(args.mcusr_parity or compact_abi),
            'virtual_app_spm':False,
            'application_self_programming':'direct_spm_whole_flash' if virtual else 'boot_entry_spm_abi' if args.app_spm else 'none',
            'virtual_boot_reset_vector_patch_required':virtual,
            'virtual_app_spm_hardware_boot_protection':False if virtual else None,
            'direct_app_spm_flash_erase_group_bytes':dev['flash_erase_group_bytes'] if virtual else None,
            'app_spm_abi':'Optiboot-8.x BOOT_START+2, r25:r24 addr/r22 opcode/r21:r20 data' if args.app_spm else None,
            'app_spm_requires_caller_interrupt_safety':bool(compact_abi),
            'app_spm_entry_byte_address':base+2 if args.app_spm else None,
            'signature_hex':''.join(f'{v:02X}' for v in dev['sig']),'bin_sha256':sha,
            'production_ready':False,
            'source_file':'optiboot_mini.S',
            'source_build_method':'compile_target_profile',
            'profile_isolated_signature':True,
            'silicon_tested':False,'avrdude_hardware_tested':False,'overclock':f_cpu>dev['max_mhz']*1000000}
        if args.mcusr_parity or compact_abi:
            result['mcusr_reset_semantics'] = 'Optiboot 8.3: preserve flags; clear WDRF only when EXTRF is also set'
        if compact_abi:
            result['mcusr_eeprom_spm_serialized'] = True
        (output/(mcu+'.json')).write_text(json.dumps(result,indent=2)+'\n')
        if virtual:print('WARNING: Virtual Boot ATtiny cannot start from reset without patching application reset and EE_RDY vectors. Do not flash .hex as a complete image.',file=sys.stderr)
        if virtual:
            print('WARNING: ATtiny SPM executes from application and is NOT hardware restricted to the app! A buggy app can overwrite its reset vectors or virtual boot code.',file=sys.stderr)
        print(f'OK {mcu}: {len(b)} bytes (code {code_bytes}) at 0x{base:04X} | {f_cpu/1e6:g} MHz / {baud} baud, U2X={uart["u2x"]}, UBRR={uart["ubrr"]}, error={uart["baud_error_percent"]:+.2f}%')
        print(f'    HEX {output/(mcu+".hex")} SHA256 {sha}')
        return result
    raise RuntimeError(f'Could not fit {mcu} in permitted boot sections: {last_message}')


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--mcu',default=os.environ.get('MINI_MCU',os.environ.get('MCU','atmega328p')))
    a.add_argument('--f-cpu',type=int)
    a.add_argument('--clock-source',choices=SUPPORTED_CLOCKS)
    a.add_argument('--baud',default=os.environ.get('BAUD_RATE','auto'))
    a.add_argument('--boot-bytes',default='auto')
    a.add_argument('--allow-overclock',action='store_true')
    a.add_argument('--allow-baud-error',action='store_true')
    a.add_argument('--legacy-eeprom-byte-address',action='store_true',
        help='ATmega64A/128A only: match old AVRDUDE STK500v1 EEPROM byte addressing (2022 and earlier clients may differ)')
    a.add_argument('--compact-signature',action='store_true',
        help='512-byte compatibility variant: both signatures, but no UNIVERSAL fuse/lock reads')
    a.add_argument('--app-spm',action='store_true', help='Full app-callable Optiboot SPM at BOOT_START+2 (1024 bytes or larger)')
    a.add_argument('--mcusr-parity',action='store_true',
        help='Preserve MCUSR reset flags as upstream Optiboot 8.3; clear WDRF only with EXTRF')
    a.add_argument('--virtual-app-spm',action='store_true',
        help='REMOVED: ATtiny can execute SPM directly; this obsolete option now fails explicitly')
    a.add_argument('--app-spm-512',action='store_true', help='512B SPM ABI for validated 8/16/32KiB classical ATmega 64/128B-page devices; no GET_SIGN_ON string or SET_PARAMETER')
    a.add_argument("--signature-source", choices=["constants", "hardware", "auto"], default="constants",
        help="Signature source: legacy footer, chip SIGRD+LPM, or audited chip-select auto")
    a.add_argument('--compact-sign-on',action='store_true',
        help='Exact AVR061 GET_SIGN_ON for compact images (requires additional code and 7 footer bytes)')
    a.add_argument('--compact-tiny',action='store_true', help='512..1024-byte erase-group-aligned Virtual Boot with compact STK500 protocol and 5B signature footer; no APP SPM ABI')
    a.add_argument('--compact-banked',action='store_true', help='Experimental compact SPM ABI and EEPROM core on 128/256KiB banked ATmega, 1024B physical boot')
    a.add_argument('--compact-644',action='store_true', help='Legacy alias: compact 64KiB family restricted to ATmega644/644A/644P/644PA')
    a.add_argument('--compact-64k',action='store_true', help='64KiB ATmega644/640/64A compact 512B payload in the physical 1024B Boot section')
    a.add_argument('--fuse-lock-read', action='store_true', help='Add real STK_UNIVERSAL fuse/lock read (extra bytes: requires the physical 1024B Boot area)')
    a.add_argument('--universal-signature',action='store_true',
        help='Respond to stk500v1 UNIVERSAL 30 00 <index> 00 signature requests; full-featured image may require 1024B BOOTSZ (328P standard remains unchanged)')
    a.add_argument('--toolchain',choices=['auto','clang','gcc'],default='auto')
    a.add_argument('--output-dir')
    a.add_argument('--verify-baseline',action='store_true')
    a.add_argument('--list-chips',action='store_true')
    args=a.parse_args()
    if args.list_chips:
        for chip,info in DEVICES.items():print(f'{chip:14} {info["flash"]//1024:2} KiB flash  {info["page"]:3}B page  {info["eeprom"]:4}B EEPROM  {info["max_mhz"]}MHz rated')
        return
    build(args)
if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,subprocess.CalledProcessError,OSError) as e:
        print('ERROR:',e,file=sys.stderr);sys.exit(1)
