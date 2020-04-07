import pygatt
import threading
import struct
import time
import queue
from retry import retry
from binascii import hexlify, unhexlify

import anovamqtt.AnovaStatus as AnovaStatus
import anovamqtt.MQTTController as MQTTController

import json

#Constants for commands and devices
DEVICE_PRIMARY_UUID = "0e140001-0af1-4582-a242-773e63054c68"
DEVICE_NOTIFICATION_CHAR_UUID = "0e140002-0af1-4582-a242-773e63054c68"
DEVICE_NOTIFICATION_CHAR_UUID2 = "0e140003-0af1-4582-a242-773e63054c68"
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
# DEFAULT_LOGGING_FORMATER = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
# DEFAULT_HANDLER = logging.StreamHandler()
# DEFAULT_HANDLER.setFormatter(DEFAULT_LOGGING_FORMATER)
# DEFAULT_LOGGER = logging.getLogger('anovamqtt_default_logger')
# DEFAULT_LOGGER.addHandler(DEFAULT_HANDLER)
# DEFAULT_LOGGER.setLevel(logging.INFO)

class AnovaMQTT(object):

    def __init__(self, config=None, debug=False):
        self._dev = None
        self._adapter = pygatt.GATTToolBackend()
        

        self._config = config
        self._command_queue = queue.Queue(maxsize=20)
        
        logging.getLogger('pygatt').setLevel("WARNING")#self._config.get('main', 'log_level'))

        self.status = AnovaStatus.AnovaStatus()
        self._mqtt = MQTTController.MQTTController(config = config, command_callback=self.mqtt_command)

        self.valid_states = [
            "off",
            "cool",
            "heat"
        ]

        self.auto_connect()
        threading.Thread(target=self.background_worker, args=(1,),daemon=True).start()

        
    def __del__(self):
        logging.debug('Destructing anovamqtt object %s'%str(self))
        self.disconnect()

    def dump_status(self):
        json_status = json.dumps(self.status.__dict__, sort_keys=True,
                                 indent=4)
        print(json_status)

    def mqtt_command(self, command, data):
        # The MQTT library processes incoming messages in a background
        # thread, so this callback will always be run separately to
        # the main Bluetooth message handling. We use a queue to pass
        # inbound messages to the Bluetooth function, to ensure only
        # one thread is trying to use the connection to the Anova.
        self._command_queue.put([command, data])

    def callback(self, handle, value):

        # if message contains current target temperature
        if(value.startswith(b'\x01\x05\x04\x08')):
            self.status.target_temp = self.decode_temp(hexlify(value)[8:12])
            return

        if(value.startswith(b'\x01\x0a')):
            self.status.current_temp = self.decode_current_temp(hexlify(value)[12:16])
            return
        
        # if message contains current state
        if(value.endswith(b'\x07\x00')):
            if (value.startswith(b'\x0a\x07')):
                self.status.state = self.valid_states[2]
                return
            elif (value.startswith(b'\x0a\x06')):
                self.status.state = self.valid_states[1]
                return

        # is message contains current temperature (?) likely coil temp
        if(value.startswith(b'\x0a\x06\x08')):
            #logging.info(hexlify(value))
            return
        #logging.info(hexlify(value))
    def background_worker(self, name):
        while(1):
            if(self.is_connected()):
                self.request_keep_alive()

    @retry()
    def auto_connect(self, timeout=DEFAULT_TIMEOUT_SEC):
        if self.is_connected():
            errmsg = 'Already connected to a device: %s'%str(self._dev)
            logging.error(errmsg)
            raise RuntimeError(errmsg)
        logging.info('Auto connecting, timeout set to: %.2f'%timeout)
        anova_dev_props = self.discover(timeout=timeout)
        logging.debug('Found these Anova devices: %s'%str(anova_dev_props))
        if len(anova_dev_props) < 1:
            errmsg = 'Did not find Anova device in auto discover mode.'
            logging.error(errmsg)
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
                    logging.error('BLE Scan failed due to adapter not able to reset')
                    raise e
                logging.info('Resetting BLE Adapter, retrying scan. {0} retries left'.format(
                    retries - retry_count))
                self._adapter.reset()
        if list_all:
            return devices
        return list(filter(lambda dev: dev_mac_pattern.match(dev['address']), devices))

    @retry(delay=15)
    def connect_device( self, dev_prop, notification_uuid=DEVICE_NOTIFICATION_CHAR_UUID, notification_uuid2=DEVICE_NOTIFICATION_CHAR_UUID2):
        """This function connects to an Anova device and register for notification

        Args:
            dev_prop: device property that is a dict with 'name' and 'address' as keys .
                      e.g: {'name': 'ffs', 'address': '01:02:03:04:05:10'}
            notification_uuid: the notification uuid to subscribe to, default to `DEVICE_NOTIFICATION_CHAR_UUID`_
                               this value should be constant for all Anova Bluetooth-only devices and can be discover
                               with gatt tool.
        
        """
        logging.info('Starting anovamqtt BLE adapter')
        self._adapter.start()
        logging.info('Connecting to Anova device: %s'%str(dev_prop))
        self._dev = self._adapter.connect(dev_prop['address'])
        logging.info('Connected to: %s'%str(dev_prop))
        self._dev.subscribe(notification_uuid, callback=self.callback, indication=False)
        logging.info('Subscribed to notification handle: %s'%notification_uuid)
        self._dev.subscribe(notification_uuid2, callback=self.callback, indication=False)
        logging.info('Subscribed to notification handle: %s'%notification_uuid2)
        self.status.state = self.valid_states[1]


    def disconnect(self):
        """This function disconnects from an existing Anova device and stops the BLE adapter
        
        """
        logging.info('Stopping anovamqtt BLE adapter...')
        if self._adapter: self._adapter.stop()
        if self._dev:
            self._dev = None
        logging.info('Stopped')
        self.status.state = self.valid_states[0]


    def is_connected(self):
        """This function checks if an Anova device is already connected

        Returns: 
            bool: True if the device is already set
        """
        return self._dev is not None

    def request(self, handle, value):
        logging.debug('Requesting: %s' % value)
        try:
            self._dev.char_write_handle(handle=handle, value=value , wait_for_response=False)
        except (pygatt.exceptions.NotConnectedError, pygatt.exceptions.NotificationTimeout):
            self.status.state = self.valid_states[2]
            logging.info("Reconnecting...")
            self.status.state = self.valid_states[0]
            if(self.is_connected()):
                self.disconnect()
            self.auto_connect()

    def encode_temp(self, value):
        return hex(int(((value*10)%128)+128)<<8 | int(value*10/128))[2:]

    def decode_temp(self, value):
        value = unhexlify(value)
        return ((int(hexlify(value[1:]), 16)*128) + (int(hexlify(value[:1]),16) - 128)) / 10
    
    def decode_current_temp(self, value):
        value = unhexlify(value)
        return ((int(hexlify(value[1:]), 16)*128) + (int(hexlify(value[:1]),16) - 128)) / 100

    def set_temp(self, temp):
        request_string = "01050308"+self.encode_temp(temp)+"00"
        logging.warning("Setting Temp: %s encoded: %s" % (temp,request_string) )
        self.request(DEVICE_NOTIFICATION_CHAR_HANDLE, bytearray(unhexlify(request_string)))

    def start(self, ):
        logging.info('Setting state: heat')
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020a00")))

    def stop(self, ):
        logging.info('Setting state: cool')
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020b00")))

    def request_current_temp(self, ):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020500")))

    def request_current_set_temp(self, ):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(unhexlify("01020400")))

    def request_keep_alive(self,):
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(b'\x01\x02\x05\x00'))
        time.sleep(.05)
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(b'\x01\x02\x04\x00'))
        time.sleep(.05)
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(b'\x01\x02\x07\x00'))
        time.sleep(.05)
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(b'\x01\x02\x1a\x00'))
        time.sleep(.05)
        self.request(handle=DEVICE_NOTIFICATION_CHAR_HANDLE, value=bytearray(b'\x01\x02\x12\x00'))


    def run(self):
        # Every time through the loop, we check for queued commands
        # received via MQTT. If there are any, run those. If not,
        # just fetch status. Then rest a bit between runs.
        # Note: This should be THE ONLY place that actually talks
        # to the Anova.
        # Every time through the loop we increment status_count
        status_count = 0
        # How long to sleep at the end of the loop (in seconds)
        loop_delay = 0.1
        # Send status after this many iterations through the loop
        status_max = 5
        while True:
            next_command = None
            if (not self._command_queue.empty()):
                try:
                    next_command = self._command_queue.get_nowait()
                except queue.Empty:
                    # This shouldn't happen with only one queue
                    # consumer, but catch it and move on if so.
                    pass

            if (next_command is not None):
                if (next_command[0] == 'run'):
                    logging.info('Received MQTT Run request: {}'.format(next_command[1]))
                    if (next_command[1] ==  self.valid_states[2]):
                        self.start()
                    elif (next_command[1] == self.valid_states[1]):
                        self.stop()
                    else:
                        logging.warning('Unknown mode for run command: {}'.format(next_command[1]))
                elif (next_command[0] == 'temp'):
                    logging.info('Received MQTT Temp request: {}'.format(next_command[1]))
                    try:
                        target_temp = float(next_command[1])
                    except ValueError:
                        # Couldn't parse it, don't care
                        logging.warning('Cannot parse temp: {}'.format(next_command[1]))
                        target_temp = 0
                    # Bounds checking, yes these are hard coded
                    # (based on fahrenheit or Celscius!) from the Anova website
                    if self.status.temp_unit == "F":
                        if (target_temp >= 32 and target_temp <= 197):
                            self.set_temp(target_temp)
                    elif self.status.temp_unit == "C":
                        if (target_temp >= 0 and target_temp <= 92):
                            self.set_temp(target_temp)
                # elif (next_command[0] == 'timer_run'):
                #     if (next_command[1] == 'running'):
                #         self._anova.start_timer()
                #     elif (next_command[1] == 'stopped'):
                #         self._anova.stop_timer()
                #     else:
                #         logging.warning('Unknown mode for timer_state command: {}'.format(next_command[1]))
                # elif (next_command[0] == 'timer'):
                #     try:
                #         target_timer = int(next_command[1])
                #     except ValueError:
                #         # Couldn't parse it, don't care
                #         target_timer = 0
                #     selv._anova.set_timer(target_timer)
                else:
                    logging.error('Unknown command received: {}'.format(next_command[0]))

            if (status_count >= status_max):
                json_status = json.dumps(self.status.__dict__, sort_keys=True)
                json_timer_status = json.dumps(self.status.__dict__, sort_keys=True)

                self._mqtt.publish_message(self._config.get('mqtt', 'status_topic'), json_status)
                self._mqtt.publish_message(self._config.get('mqtt', 'status_timer'), json_timer_status)
                status_count = 0
            else:
                status_count = status_count+1

            time.sleep(loop_delay)
