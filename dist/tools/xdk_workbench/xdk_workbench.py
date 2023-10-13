import os
import time
from enum import Enum
import re

import serial.tools.list_ports
from serial import PARITY_NONE, STOPBITS_ONE
from xmodem import XMODEM

BOOTLOADER_VERSION_MATCHER = re.compile(b".*BOOTLOADER version V(\\d+)\\.(\\d+)\\.(\\d+).*")
BOOTLOADER_CORE_ID_MATCHER = re.compile(b".*ID(.*)")

PORT_NAME = '/dev/ttyACM0'
BINARY_PATH = '/mnt/data/Schule/PEG/RIOT/examples/hello-world/bin/bosch-xdk110/hello-world.bin'

ser = serial.Serial()
ser.port = PORT_NAME
ser.baudrate = 19200
ser.parity = PARITY_NONE
ser.stopbits = STOPBITS_ONE


class DeviceMode(Enum):
    BOOTLOADER = 0
    APPLICATION = 1
    DEBUG = 2
    UNKNOWN = 3


class Command(Enum):
    UPLOAD = ("u", DeviceMode.BOOTLOADER)
    BOOT = ("b", DeviceMode.BOOTLOADER)
    VERIFY = ("c", DeviceMode.BOOTLOADER)
    DEBUG = ("l", DeviceMode.BOOTLOADER)
    RESET = ("r", DeviceMode.BOOTLOADER)
    INFO = ("i", DeviceMode.BOOTLOADER)
    GOTO_BOOTLOADER = ("#reBoot$", DeviceMode.APPLICATION)
    REBOOT = ("#reSet$", DeviceMode.APPLICATION)


def get_bootloader_type_by_version(version):
    for bootloader in BootloaderType:
        if bootloader.value[3] == version:
            return bootloader
    return None


class BootloaderType(Enum):
    WITH_FOTA = ("With FOTA Header", "0x00020000", "0x00020200", (0, 0, 0), 917504)
    WITHOUT_FOTA = ("Without FOTA Header", "0x00010000", (0, 0, 0), 983040)
    Version_0_0_9 = ("0.0.9", "0x00010000", (0, 0, 9), 983040)
    Version_0_0_10 = ("0.0.10", "0x00010000", (0, 0, 10), 983040)
    Version_1_0_0 = ("1.0.0", "0x00020000", "0x00020200", (1, 0, 0), 614400)
    Version_1_1_0 = ("1.1.0", "0x00020000", "0x00020200", (1, 1, 0), 614400)
    Version_1_2_0 = ("1.2.0", "0x00020000", "0x00020200", (1, 2, 0), 917504)


def extract_bootloader_core_id(response):
    matcher = BOOTLOADER_CORE_ID_MATCHER.match(response)
    if matcher:
        return matcher.group(1).strip()
    else:
        return None


def extract_bootloader_version(response):
    matcher = BOOTLOADER_VERSION_MATCHER.match(response)
    if matcher:
        return int(matcher.group(1)), int(matcher.group(2)), int(matcher.group(3))
    else:
        return 0, 0, 0


def get_xdk_device_mode():
    xdk_port = None
    for port in serial.tools.list_ports.comports():
        if port.device == PORT_NAME:
            xdk_port = port
            break
    if "Application" in xdk_port.description:
        return DeviceMode.APPLICATION
    elif "Bootloader" in xdk_port.description:
        return DeviceMode.BOOTLOADER
    else:
        return DeviceMode.UNKNOWN


def is_xmodem_response(data):
    return data == 1 or data == 4 or data == 6 or data == 21 or data == 67 or data == 24 or data == 26


def is_bootloader_response(trim: str):
    return trim == "i" or trim == "c" or trim == "CRC" or trim.startswith("0000") and len(
        trim) == 8 or trim.equalsIgnoreCase("Ready") or trim.equalsIgnoreCase("u") or trim.equalsIgnoreCase("b")


def getc(size, timeout=1):
    data = ser.read(size)
    if is_xmodem_response(data[0]) and len(data) == 1:
        return data or None
    else:
        msg = data + ser.readline()
        print(msg)
    return getc(size, timeout)


def putc(data, timeout=1):
    return ser.write(data)  # note that this ignores the timeout


def send_command(command: Command):
    mode = get_xdk_device_mode()
    if mode == command.value[1]:
        ser.write(command.value[0].encode("ascii"))
    else:
        if mode == DeviceMode.APPLICATION:
            ser.write(Command.GOTO_BOOTLOADER.value[0].encode("ascii"))
        else:
            ser.write(Command.BOOT.value[0].encode("ascii"))


def wait_for_line(matcher):
    line = ser.readline()
    while not matcher(line):
        time.sleep(0.05)
        line = ser.readline()
    return line


def info_matcher(line):
    return line.startswith(b"BOOTLOADER version")


def ready_matcher(line):
    return b"Ready" in line


def checksum_matcher(line):
    return line.startswith(b"0000") and len(line) == 8 or line.startswith(b"CRC0000") and len(line) == 11


ser.open()
send_command(Command.INFO)
info = wait_for_line(info_matcher)
version = extract_bootloader_version(info)
bootloader_type = get_bootloader_type_by_version(version)
binary_size = os.path.getsize(BINARY_PATH)
if binary_size > bootloader_type.value[4]:
    print("Flashing aborted due to not supported firmware size for XMODEM file transfer.\n\tThe supported size for "
          "this Bootloader is {0} Bytes.\n\tSize of {1} is {2} Bytes.\n\tPlease have a look into the documentation.".format(bootloader_type.value[4], BINARY_PATH, binary_size))
    exit(1)
send_command(Command.UPLOAD)
wait_for_line(ready_matcher)
modem = XMODEM(getc, putc)
with open(BINARY_PATH, "rb") as f:
    modem.send(f)
send_command(Command.VERIFY)
