"""
This module defines a library for accessing the functionality of the
Logitech Litra Glow and Logitech Litra Beam
"""
import os
import logging
import math
import array
import usb.core
import usb.util
from llgd.config.llgd_config import LlgdConfig

VENDOR_ID = 0x046d
LITRA_PRODUCTS = [{'name': 'Glow',
                   'id': 0xc900,
                   'endpoint': 0x02,
                   'buffer_length': 64},

                  {'name': 'Beam',
                   'id': 0xc901,
                   'endpoint': 0x01,
                   'buffer_length': 32},
                  ]

LIGHT_OFF = 0x00
LIGHT_ON = 0x01
TIMEOUT_MS = 3000
MIN_BRIGHTNESS = 0x14
MAX_BRIGHTNESS = 0xfa
BT_HIDRAW = "/dev/hidraw0"

endpoint_mapping = {}
buffer_length_mapping = {}
config = LlgdConfig()
devices = []


class BluetoothHidDevice:
    """Mimics usb.core.Device for fool litra-driver"""
    def __init__(self, hidraw_path, product_name):
        self.hidraw_path = hidraw_path
        self.product = product_name  # used by logging.info(product_device.product)

        class FakeCtx:
            def __getattr__(self, name): return None
            def managed_claim_interface(self, *args, **kwargs): return None
            def managed_open(self, *args, **kwargs): return None
            def dispose(self, device): pass

        self._ctx = FakeCtx()

    def __getattr__(self, name):
        if name.startswith('b') or name.startswith('i'):
            return 0
        return None

    def set_configuration(self):
        """ Requis par litra-driver pour l'USB, inutile pour le BT """
        pass

    def is_kernel_driver_active(self, interface):
        """ Souvent appelé avant de détacher un pilote """
        return False

    def detach_kernel_driver(self, interface):
        """ Requis pour l'USB sous Linux, inutile pour le BT """
        pass

    def write(self, endpoint, data, timeout=None):
        """ Redirect to bluetooth HID device."""
        try:
            with open(self.hidraw_path, "wb") as f:
                f.write(bytes(data))
            return len(data)
        except Exception as e:
            logging.error(f"Writing error on bluetooth {self.hidraw_path}: {e}")
            return 0

    def read(self, endpoint, size, timeout=None):
        return array.array('B', [0x00] * size) if 'array' in globals() else bytes([0x00] * size)


def find_devices():
    """ Search for Litra Devices
    """
    logging.info("Searching for litra devices...")
    # Classical USB search
    try:
        for product in LITRA_PRODUCTS:
            product_devices = usb.core.find(idVendor=VENDOR_ID, idProduct=product['id'], find_all=True)
            for product_device in product_devices:
                logging.info('Found USB Device "%s"', product_device.product)
                endpoint_mapping[product_device] = product['endpoint']
                buffer_length_mapping[product_device] = product['buffer_length']
                devices.append(product_device)
    except Exception as e:
        logging.warning(f"Unable to find device with USB : {e}")

    # Bluetooth search
    if os.path.exists(BT_HIDRAW):
        logging.info('Found Bluetooth Device via %s', BT_HIDRAW)

        bt_device = BluetoothHidDevice(BT_HIDRAW, "Litra Beam (Bluetooth)")

        beam_config = next((p for p in LITRA_PRODUCTS if p['id'] == 0xB901), LITRA_PRODUCTS[0])

        endpoint_mapping[bt_device] = beam_config['endpoint']
        buffer_length_mapping[bt_device] = beam_config['buffer_length']

        devices.append(bt_device)


def count():
    """ Returns a count of all devices
    """
    return len(devices)


def setup(index):
    """Sets up the device

    Raises:
        ValueError: When the device cannot be found

    Returns:
        [device, reattach]: where device is a Device object and reattach
        is a bool indicating whether the kernel driver should be reattached
    """
    dev = devices[index]
    if dev is None:
        raise ValueError('Device not found')

    reattach = False

    try:
        if dev.is_kernel_driver_active(0):
            logging.debug("kernel driver active")
            reattach = True
            dev.detach_kernel_driver(0)
        else:
            logging.debug("kernel driver not active")

    except AttributeError:
        logging.debug(
            '"is_kernel_driver_active()" method not found. Continuing')

    logging.debug(dev)
    dev.set_configuration()
    usb.util.claim_interface(dev, 0)

    return dev, reattach


def teardown(dev, reattach):
    """Tears down the device
    """
    usb.util.dispose_resources(dev)
    if reattach:
        dev.attach_kernel_driver(0)


def light_on():
    """Turns on the light
    """
    for index in range(0, count()):
        dev, reattach = setup(index)
        dev.write(endpoint_mapping[dev], [0x11, 0xff, 0x04, 0x1c, LIGHT_ON, 0x00, 0x00, 0x00, 0x00, 0x00,
                         0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], TIMEOUT_MS)
        dev.read(endpoint_mapping[dev], buffer_length_mapping[dev])
        logging.info("Light On")
        teardown(dev, reattach)


def light_off():
    """Turns off the light
    """
    for index in range(0, count()):
        dev, reattach = setup(index)
        dev.write(endpoint_mapping[dev], [0x11, 0xff, 0x04, 0x1c, LIGHT_OFF, 0x00, 0x00, 0x00, 0x00, 0x00,
                         0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], TIMEOUT_MS)
        dev.read(endpoint_mapping[dev], buffer_length_mapping[dev])
        logging.info("Light Off")
        teardown(dev, reattach)


def set_brightness(level):
    """Sets the brightness level

    Args:
        level (int): The brigtness level from 1-100. Converted between the min and
        max brightness levels supported by the device.
    """
    for index in range(0, count()):
        dev, reattach = setup(index)
        adjusted_level = math.floor(
            MIN_BRIGHTNESS + ((level/100) * (MAX_BRIGHTNESS - MIN_BRIGHTNESS)))
        dev.write(endpoint_mapping[dev], [0x11, 0xff, 0x04, 0x4c, 0x00, adjusted_level, 0x00, 0x00, 0x00, 0x00,
                         0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00], TIMEOUT_MS)
        dev.read(endpoint_mapping[dev], buffer_length_mapping[dev])
        config.update_current_state(brightness=level)
        logging.info("Brightness set to %d", level)
        teardown(dev, reattach)


def set_temperature(temp):
    """Sets the color temerpature

    Args:
        temp (int): A color temperature of between 2700 and 6500
    """
    for index in range(0, count()):
        dev, reattach = setup(index)
        byte_array = temp.to_bytes(2, 'big')
        dev.write(endpoint_mapping[dev], [0x11, 0xff, 0x04, 0x9c, byte_array[0], byte_array[1], 0x00, 0x00,
                         0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
                  TIMEOUT_MS)
        dev.read(endpoint_mapping[dev], buffer_length_mapping[dev])
        config.update_current_state(temp=temp)
        logging.info("Temperature set to %d", temp)
        teardown(dev, reattach)


find_devices()
