import pygatt
import threading
import struct
import time
from binascii import hexlify, unhexlify

#Constants for commands and devices
DEVICE_PRIMARY_UUID = "0e140001-0af1-4582-a242-773e63054c68"
DEVICE_NOTIFICATION_CHAR_UUID = "0e140002-0af1-4582-a242-773e63054c68"
DEVICE_NOTIFICATION_CHAR_HANDLE = 0X0b

# ANOVA device BLE mac pattern
import re
DEFAULT_DEV_MAC_PATTERN = re.compile('^00:81:F9:D2:13:B4')

# RESPONSES
RESP_INVALID_CMD = "Invalid Command"

# Connection settings
DEFAULT_TIMEOUT_SEC = 10
DEFAULT_CMD_TIMEOUT_SEC = 5
DEFAULT_SCAN_RETRIES = 2

# Logging format
import logging
DEFAULT_LOGGING_FORMATER = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
DEFAULT_HANDLER = logging.StreamHandler()
DEFAULT_HANDLER.setFormatter(DEFAULT_LOGGING_FORMATER)
DEFAULT_LOGGER = logging.getLogger('anovamqtt_default_logger')
DEFAULT_LOGGER.addHandler(DEFAULT_HANDLER)
DEFAULT_LOGGER.setLevel(logging.INFO)

class AnovaMQTT(object):

    def __init__(self, logger=DEFAULT_LOGGER, debug=False):
        self._dev = None
        self._adapter = pygatt.GATTToolBackend()
        self._logger = logger
        if debug: self._logger.setLevel(logging.DEBUG)
        self.auto_connect()
        threading.Thread(target=self.background_worker, args=(1,),daemon=True)
        
    def __del__(self):
        self._logger.debug('Destructing anovamqtt object %s'%str(self))
        self.disconnect()

    def callback(self, handle, value):
        print(hexlify(value))
        # if(value.endswith(b'\x18\x01')):
        #     print("notify current set temp: ")

    def background_worker(self, name):
        self.request_current_set_temp()
        self.request_current_temp()
        time.sleep(1)

    def auto_connect(self, timeout=DEFAULT_TIMEOUT_SEC):
        if self.is_connected():
            errmsg = 'Already connected to a device: %s'%str(self._dev)
            self._logger.error(errmsg)
            raise RuntimeError(errmsg)
        self._logger.info('Auto connecting, timeout set to: %.2f'%timeout)
        anova_dev_props = self.discover(timeout=timeout)
        self._logger.debug('Found these Anova devices: %s'%str(anova_dev_props))
        if len(anova_dev_props) < 1:
            errmsg = 'Did not find Anova device in auto discover mode.'
            self._logger.error(errmsg)
            raise RuntimeError(errmsg)
        # it can control 1 device only, taking the first found Anova device
        self.connect_device(anova_dev_props[0])

    def discover(self, list_all = False, dev_mac_pattern=DEFAULT_DEV_MAC_PATTERN, timeout=DEFAULT_TIMEOUT_SEC, retries=DEFAULT_SCAN_RETRIES):
        retry_count = 0
        complete = False
        while not complete:
            try:
                devices = self._adapter.scan(run_as_root=True, timeout=timeout)
                complete = True
            except pygatt.exceptions.BLEError as e:
                retry_count += 1
                if retry_count >= retries:
                    self._logger.error('BLE Scan failed due to adapter not able to reset')
                    raise e
                self._logger.info('Resetting BLE Adapter, retrying scan. {0} retries left'.format(
                    retries - retry_count))
                self._adapter.reset()
        if list_all:
            return devices
        return list(filter(lambda dev: dev_mac_pattern.match(dev['address']), devices))

    def connect_device( self, dev_prop, notification_uuid=DEVICE_NOTIFICATION_CHAR_UUID):
        """This function connects to an Anova device and register for notification

        Args:
            dev_prop: device property that is a dict with 'name' and 'address' as keys .
                      e.g: {'name': 'ffs', 'address': '01:02:03:04:05:10'}
            notification_uuid: the notification uuid to subscribe to, default to `DEVICE_NOTIFICATION_CHAR_UUID`_
                               this value should be constant for all Anova Bluetooth-only devices and can be discover
                               with gatt tool.
        
        """
        self._logger.info('Starting anovamqtt BLE adapter')
        self._adapter.start()
        self._logger.info('Connecting to Anova device: %s'%str(dev_prop))
        self._dev = self._adapter.connect(dev_prop['address'])
        self._logger.info('Connected to: %s'%str(dev_prop))
        self._dev.subscribe(notification_uuid, callback=self.callback, indication=False)
        self._logger.info('Subscribed to notification handle: %s'%notification_uuid)

    def disconnect(self):
        """This function disconnects from an existing Anova device and stops the BLE adapter
        
        """
        self._logger.info('Stopping anovamqtt BLE adapter...')
        if self._adapter: self._adapter.stop()
        if self._dev:
            self._dev = None
        self._logger.info('Stopped')

    def is_connected(self):
        """This function checks if an Anova device is already connected

        Returns: 
            bool: True if the device is already set
        """
        return self._dev is not None

    def request(self, handle, value):
        try:
            self._dev.char_write_handle(handle=handle, value=value , wait_for_response=False)
        except (pygatt.exceptions.NotConnectedError, pygatt.exceptions.NotificationTimeout):
            print("Reconnecting...")
            self.auto_connect()

    def encode_temp(self, value):
        return hex(int(((value*10)%128)+128)<<8 | int(value*10/128))[2:]

    def set_temp(self, temp):
        request_string = "01050308"+self.encode_temp(temp)+"00"
        self.request(DEVICE_NOTIFICATION_CHAR_HANDLE, bytearray(unhexlify(request_string)))

    def start(self, ):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020a00")))

    def stop(self, ):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020b00")))

    def request_current_temp(self, ):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020500")))

    def request_current_set_temp(self, ):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020400")))