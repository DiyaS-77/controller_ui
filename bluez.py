import dbus
import dbus.service
import dbus.mainloop.glib
import os
import re
import subprocess
import time
from threading import Thread
from gi.repository import GLib
import socket

from logger import Logger
from Backend_lib.Linux import hci_commands as hci
from utils import run
import constants

try:
    from gi.repository import GObject
except ImportError:
    import gobject as GObject

# Set the D-Bus main loop
dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)



class BluetoothDeviceManager:
    """
    A class for managing Bluetooth devices using the BlueZ D-Bus API.

    This manager provides capabilities for discovering, pairing, connecting,
    streaming audio (A2DP), media control (AVRCP), and removing Bluetooth devices.
    """

    def __init__(self, capability=None, log_path=None):
        """
        Initialize the BluetoothDeviceManager by setting up the system bus and adapter.
        """
        self.log = Logger("UI")
        self.log_path = log_path

        # Attributes
        self.capability = capability
        self.agent_path = constants.agent_path
        self.agent = None
        self.bus = None
        self.device_address = None
        self.stream_process = None
        self.device_path = None
        self.device_sink = None
        self.devices = {}
        self.last_session_path = None
        self.opp_process = None
        self.bd_address = None
        self.controllers_list = {}
        self.handles = None
        self.bluetoothd_process = None
        self.pulseaudio_process = None
        self.hcidump_process = None
        self.bluetoothd_log_name = None
        self.pulseaudio_log_name = None
        self.hcidump_log_name = None
        self.start_dbus_service()
        self.start_bluetoothd_logs()
        self.setup_bluetooth_agent()
        self.start_pulseaudio_logs()


    #----------INITIALIZING DBUS------------------#
    def _wait_for_bluez(self, timeout=10):
        """Wait for BlueZ to appear on D-Bus.

        Args:
            timeout (int): Maximum number of seconds to wait for BlueZ to appear. Default is 10.
        """
        self._connect_system_bus_with_retry()
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                names = self.bus.list_names()
                if constants.bluez_service in names:
                    return
            except RuntimeError as e:
                self.log.error(f"[ERROR] {e}")

    def _connect_system_bus_with_retry(self, retries=5, delay=0.5):
        for attempt in range(retries):
            try:
                self.bus = dbus.SystemBus()
                return
            except dbus.exceptions.DBusException as e:
                self.log.info(f"[WARN] Retry {attempt + 1}/{retries} - D-Bus not ready: {e}")
                time.sleep(delay)
        raise RuntimeError("Failed to connect to D-Bus after multiple retries.")


    def start_dbus_service(self):
        """
        Starts the D-Bus system daemon and waits for the system socket to become available.

        This method launches the D-Bus daemon using a predefined command from `constants.dbus_command`,
        then continuously polls for the availability of the D-Bus system socket within a timeout window.
    I   if the socket becomes available, the method logs success; otherwise, it raises a RuntimeError.
        """

        self.log.info("Starting D-Bus service...")
        self.dbus_process = subprocess.Popen(constants.dbus_command, shell=True)

        # Wait for D-Bus system socket to become available
        dbus_socket_path = '/usr/local/bluez/dbus-1.12.20/var/run/dbus/system_bus_socket'
        timeout = 10
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                # Try to connect to the socket directly
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(dbus_socket_path)
                s.close()
                self.log.info("D-Bus system socket is now available.")
                break
            except socket.error:
                time.sleep(0.3)
        else:
            self.log.error(f"Timed out waiting for D-Bus socket at {dbus_socket_path}")
            raise RuntimeError("D-Bus system socket did not become available.")

        self.log.info("D-Bus service started successfully.")


    def initialize_adapter(self, interface):
        """
        Initializes the Bluetooth adapter (controller) for the given interface.

        Args:
            interface (str): The name of the Bluetooth interface (e.g., 'hci0')
        """
        self.interface = interface
        if self.interface:
            self.adapter_path = f'/org/bluez/{self.interface}'
            self.adapter_proxy = self.bus.get_object(constants.bluez_service, self.adapter_path)
            self.adapter = dbus.Interface(self.adapter_proxy, constants.adapter_iface)

    def setup_bluetooth_agent(self):
        """
        Waits for BlueZ to appear on D-Bus and registers the Bluetooth agent.
        Raises an exception if any step fails.
        """
        self._wait_for_bluez()
        self.register_agent()
        self.log.info("Bluetooth agent registered successfully.")

    def start_discovery(self):
        """
        Start Bluetooth device discovery.
        """
        self.adapter.StartDiscovery()

    def stop_discovery(self):
        """
        Stop Bluetooth device discovery.
        """
        self.adapter.StopDiscovery()

    #-----------AGENT----------------#
    def set_trusted(path):
        """
        Set the Bluetooth device at the given D-Bus path as trusted.

        Args:
            path (str): The D-Bus object path of the device.
        returns:
        	None
        """
        props = dbus.Interface(bus.get_object(constants.bluez_service, path), constants.props_iface)
        props.Set(constants.device_iface, "Trusted", True)

    def raise_rejected_error(message="Rejected by user"):
        """
        Raises a dbus.DBusException with the BlueZ Rejected error name.
        """
        error = dbus.DBusException(message)
        error._dbus_error_name = "org.bluez.Error.Rejected"
        raise error

    def set_exit_on_release(self, exit_on_release):
        """
        Set whether the agent should terminate the main loop on release.

        Args:
            exit_on_release (bool): If True, stop the main loop on release.
        returns:
            None
        """
        self.exit_on_release = exit_on_release

    @dbus.service.method(constants.agent_interface, in_signature="", out_signature="")
    def Release(self):
        """
        Called when the agent is released by BlueZ.

        args: None
        returns: None
        """
        self.log.info("Release")
        if self.exit_on_release:
            mainloop.quit()

    @dbus.service.method(constants.agent_interface, in_signature="os", out_signature="")
    def AuthorizeService(self, device, uuid):
        """
        Ask the user to authorize a service request.

        Args:
            device (str): The device object path.
            uuid (str): The UUID of the requested service.
        returns:
            None
        """
        self.log.info("AuthorizeService (%s, %s)" % (device, uuid))
        set_trusted(device)
        return

    @dbus.service.method(constants.agent_interface, in_signature="o", out_signature="s")
    def RequestPinCode(self, device):
        """
        Ask the user to enter a PIN code for pairing.

        Args:
            device (str): The device object path.

        Returns:
            str: The PIN code entered by the user.
        """
        self.log.info("RequestPinCode (%s)" % (device))
        set_trusted(device)
        return "0000"

    @dbus.service.method(constants.agent_interface, in_signature="o", out_signature="u")
    def RequestPasskey(self, device):
        """
        Ask the user to enter a numeric passkey.

        Args:
            device (str): The device object path.

        Returns:
            dbus.UInt32: The passkey as a 32-bit unsigned integer.
        """
        self.log.info("RequestPasskey (%s)" % (device))
        set_trusted(device)
        return dbus.UInt32(123456)

    @dbus.service.method(constants.agent_interface, in_signature="ouq", out_signature="")
    def DisplayPasskey(self, device, passkey, entered):
        """
        Display the passkey and how many digits have been entered so far.

        Args:
            device (str): The device object path.
            passkey (int): The passkey to display.
            entered (int): Number of digits entered so far.
        returns:
            None
        """
        self.log.info("DisplayPasskey (%s, %06u entered %u)" % (device, passkey, entered))

    @dbus.service.method(constants.agent_interface, in_signature="os", out_signature="")
    def DisplayPinCode(self, device, pincode):
        """
        Display a PIN code for manual entry.

        Args:
            device (str): The device object path.
            pincode (str): The PIN code to display.
        returns:
            None
        """
        self.log.info("DisplayPinCode (%s, %s)" % (device, pincode))

    @dbus.service.method(constants.agent_interface, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device, passkey):
        """
        Ask the user to confirm the displayed passkey.

        Args:
            device (str): The device object path.
            passkey (int): The passkey to confirm.
        returns:
            None
        """
        self.log.info("RequestConfirmation (%s, %06d)" % (device, passkey))
        set_trusted(device)
        return

    @dbus.service.method(constants.agent_interface, in_signature="o", out_signature="")
    def RequestAuthorization(self, device):
        """
        Ask the user to authorize pairing with the device.

        Args:
            device (str): The device object path.
        returns:
            None
        """
        self.log.info("RequestAuthorization (%s)" % (device))
        set_trusted(device)
        return

    @dbus.service.method(constants.agent_interface, in_signature="", out_signature="")
    def Cancel(self):
        """
        Called if the pairing request was canceled.

        args: None
        returns: None
        """
        self.log.info("Cancel")

    def register_agent(self):
        """
        Starts the D-Bus main loop and registers the custom Bluetooth agent with BlueZ.

        This sets up the D-Bus connection, registers the agent with the 1 interface,
        and runs the GLib main loop in a background thread.

        args: None
        returns: None
        """
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        bus = self.bus

        # Create and register your existing Agent
        self.mainloop = GLib.MainLoop()

        # Register the agent with BlueZ
        manager = dbus.Interface(
            bus.get_object(constants.bluez_service, constants.bus_path),
            constants.agent_manager_iface
        )
        manager.RegisterAgent(self.agent_path, self.capability)
        manager.RequestDefaultAgent(self.agent_path)
        self.log.info(f"[Agent] Registered with capability: {self.capability}")

        # Run the GLib main loop in a background thread
        thread = Thread(target=self.mainloop.run, daemon=True)
        thread.start()

    def unregister_agent(self):
        """
        Stops the D-Bus main loop if it is running.

        This effectively unregisters the agent and ends the background thread handling the loop.

        args: None
        returns: None
        """
        if self.mainloop and self.mainloop.is_running():
            self.mainloop.quit()

    #---------CONTROLLER DETAILS----------------------#
    def get_controllers_connected(self):
        """
        Returns the list of controllers connected to the host.

        args : None
        Returns:
            dict: Dictionary with BD address as key and interface as value.
        """
        result = run(self.log, 'hciconfig -a | grep -B 2 \"BD A\"')
        result = result.stdout.split("--")
        if result[0]:
            for res in result:
                res = res.strip("\n").replace('\n', '')
                if match := re.match('(.*):	Type:.+BD Address: (.*)  ACL(.*)', res):
                    self.controllers_list[match[2]] = match[1]
        self.log.info("Controllers {} found on host".format(self.controllers_list))
        return self.controllers_list

    def get_controller_interface_details(self):
        """
        Gets the controller's interface and bus details.

        args: None
        Returns:
            str: Interface and Bus information.
        """
        self.interface = self.controllers_list[self.bd_address]
        result = run(self.log, f"hciconfig -a {self.interface} | grep Bus")
        return f"Interface: {self.interface} \t Bus: {result.stdout.split('Bus:')[1].strip()}"

    def convert_mac_little_endian(self, address):
        """
        Converts MAC (BD) address to little-endian format.

        Args:
            address (str): BD address in normal format (e.g., 'AA:BB:CC:DD:EE:FF').

        Returns:
            str: BD address in little-endian format (e.g., 'FF EE DD CC BB AA').
        """
        addr = address.split(':')
        addr.reverse()
        return ' '.join(addr)

    def convert_to_little_endian(self, num, num_of_octets):
        """
        Converts a number to little-endian hexadecimal representation.

        Args:
            num (int or str): Number to be converted.
            num_of_octets (int): Number of octets to format the result.

        Returns:
            str: Little-endian formatted hex string.
        """
        data = None
        if isinstance(num, str) and '0x' in num:
            data = num.replace("0x", "")
        elif isinstance(num, str) and '0x' not in num:
            data = int(num)
            data = str(hex(data)).replace("0x", "")
        elif isinstance(num, int):
            data = str(hex(num)).replace("0x", "")
        while True:
            if len(data) == (num_of_octets * 2):
                break
            data = "0" + data
        out = [(data[i:i + 2]) for i in range(0, len(data), 2)]
        out.reverse()
        return ' '.join(out)

    def run_hci_cmd(self, ogf, command, parameters=None):
        """
        Executes an HCI command with provided parameters.

        Args:
            ogf (str): Opcode Group Field (e.g., '0x03').
            command (str): Specific HCI command name.
            parameters (list): List of parameters for the command.

        Returns:
            subprocess.CompletedProcess: Result of command execution.
        """
        _ogf = ogf.lower().replace(' ', '_')
        _ocf_info = getattr(hci, _ogf)[command]
        hci_command = 'hcitool -i {} cmd {} {}'.format(self.interface, hci.hci_commands[ogf], _ocf_info[0])
        for index in range(len(parameters)):
            param_len = list(_ocf_info[1][index].values())[1] if len(
                _ocf_info[1][index].values()) > 1 else None
            if param_len:
                parameter = self.convert_to_little_endian(parameters[index], param_len)
            else:
                parameter = parameters[index].replace('0x', '')
            hci_command = ' '.join([hci_command, parameter])
        self.log.info(f"Executing command: {hci_command}")
        return run(self.log, hci_command)

    def get_connection_handles(self):
        """
        Retrieves active Bluetooth connection handles for the current interface.

        args: None
        Returns:
            dict: Dictionary of connection handles with hex values.
        """
        hcitool_con_cmd = f"hcitool -i {self.interface} con"
        self.handles = {}
        result = run(self.log, hcitool_con_cmd)
        results = result.stdout.split('\n')
        for line in results:
            if 'handle' in line:
                handle = (line.strip().split('state')[0]).replace('< ', '').strip()
                self.handles[handle] = hex(int(handle.split(' ')[-1]))
        return self.handles


    def run_command(self, command, log_file=None):
        """
        Executes a shell command and captures its output.

        Args:
            command (str): The shell command to execute.
            log_file (str, optional): Path to a log file to write output (currently unused).

        Returns:
            subprocess.CompletedProcess: The completed process object containing stdout, stderr, and return code.
        """

        output = subprocess.run(command, shell=True, capture_output=True, text=True)
        self.log.info(f"Command: {command}\nOutput: {output.stdout}")
        return output



    def start_bluetoothd_logs(self):
        """
        Starts the bluetoothd service and begins logging its output.

        Returns:
            str: The path to the bluetoothd log file.
        """

        self.bluetoothd_log_name = os.path.join(self.log_path, "bluetoothd.log")
        subprocess.run("pkill -f bluetoothd", shell=True)

        self.log.info(f"[INFO] Starting bluetoothd logs...")
        self.bluetoothd_process = subprocess.Popen(
            constants.bluetoothd_command.split(),
            stdout=open(self.bluetoothd_log_name, 'a+'),
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )


        self.log.info(f"[INFO] Bluetoothd logs started: {self.bluetoothd_log_name}")
        return True

    def start_pulseaudio_logs(self):
        """
        Starts the PulseAudio daemon and begins logging its output.

        Returns:
            str: The path to the pulseaudio log file.
        """

        self.pulseaudio_log_name = os.path.join(self.log_path, "pulseaudio.log")
        subprocess.run("pkill -f pulseaudio", shell=True)

        self.log.info(f"[INFO] Starting pulseaudio logs...")
        self.pulseaudio_process = subprocess.Popen(
            constants.pulseaudio_command.split(),
            stdout=open(self.pulseaudio_log_name, 'a+'),
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )


        self.log.info(f"[INFO] Pulseaudio logs started: {self.pulseaudio_log_name}")
        return True

    def start_dump_logs(self, interface):
        """
        Starts hcidump logging for a given Bluetooth interface.

        Args:
            interface (str): The Bluetooth interface (e.g., 'hci0') to capture logs from.

        Returns:
            str | bool: Path to the log file if successful, False if an error occurs or interface is not provided.
        """
        try:
            if not interface:
                self.log.info("[ERROR] Interface is not provided for hcidump")
                return False

            subprocess.run(
                constants.hciconfig_up_command.format(interface=interface).split(),
                capture_output=True
            )

            self.hcidump_log_name = os.path.join(self.log_path, f"{interface}_hcidump.log")
            self.log.info(f"[INFO] Starting hcidump: {constants.hcidump_command}")

            self.hcidump_process = subprocess.Popen(
                constants.hcidump_command.format(interface=interface).split(),
                stdout=open(self.hcidump_log_name, 'a+'),
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True
            )

            self.log.info(f"[INFO] hcidump process started: {self.hcidump_log_name}")
            return True

        except Exception as e:
            self.log.info(f"[ERROR] Failed to start hcidump: {e}")
            return False

    def stop_bluetoothd_logs(self):
        """
        Stops the bluetoothd logging subprocess if it is running.

        Returns:
            bool: True if the process was terminated or already not running, False otherwise.
        """
        self.log.info("[INFO] Stopping bluetoothd logs...")

        if not self.bluetoothd_process:
            self.log.info("No bluetoothd process to stop.")
            return False

        if self.bluetoothd_process.poll() is not None:
            self.log.info("bluetoothd process already terminated.")
            self.bluetoothd_process = None
            return True

        try:
            self.bluetoothd_process.terminate()
            self.bluetoothd_process.wait(timeout=5)
            self.log.info("bluetoothd logs stopped successfully.")
        except subprocess.TimeoutExpired:
            self.log.info("Termination timed out. Killing bluetoothd process...")
            self.bluetoothd_process.kill()
            self.bluetoothd_process.wait()
            self.log.info("bluetoothd process killed.")

        self.bluetoothd_process = None
        return True


    def stop_pulseaudio_logs(self):
        """
        Stops the pulseaudio logging subprocess if it is running.

        Returns:
            bool: True if the process was terminated or already not running, False otherwise.
        """
        self.log.info("[INFO] Stopping pulseaudio logs...")

        if not self.pulseaudio_process:
            self.log.info("No pulseaudio process to stop.")
            return False

        if self.pulseaudio_process.poll() is not None:
            self.log.info("pulseaudio process already terminated.")
            self.pulseaudio_process = None
            return True

        try:
            self.pulseaudio_process.terminate()
            self.pulseaudio_process.wait(timeout=5)
            self.log.info("pulseaudio logs stopped successfully.")
        except subprocess.TimeoutExpired:
            self.log.info("Termination timed out. Killing pulseaudio process...")
            self.pulseaudio_process.kill()
            self.pulseaudio_process.wait()
            self.log.info("pulseaudio process killed.")

        self.pulseaudio_process = None
        return True


    def stop_dump_logs(self):
        """
        Stops the hcidump logging process, if running.

        Returns:
            bool: True if the process was stopped or not running, False if an error occurred.
        """

        if self.hcidump_process:
            self.log.info("[INFO] Stopping HCI dump logs")
            try:
                self.hcidump_process.terminate()
                self.hcidump_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.hcidump_process.kill()
                self.hcidump_process.wait()
            self.hcidump_process = None
            self.log.info("[INFO] HCI dump logs stopped successfully")

        if self.hcidump_process:
            try:
                result = subprocess.run(['pgrep', '-f', f'hcidump.*{self.interface}'],
                                        capture_output=True, text=True)
                if result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        subprocess.run(['kill', '-TERM', pid])
                    time.sleep(1)
                    for pid in pids:
                        subprocess.run(['kill', '-KILL', pid])
            except Exception as e:
                self.log.info(f"[ERROR] Error killing hcidump: {e}")
                return False


        return True

    def get_controller_details(self, interface=None):
        """
        Retrieves and parses detailed information about a given Bluetooth controller interface.

        Args:
            interface (str, optional): The Bluetooth interface (e.g., "hci0"). If not provided,
                                       the method uses the last known interface value.

        Returns:
            dict: A dictionary containing the controller details. Keys include:
                - 'BD_ADDR': Bluetooth MAC address
                - 'Name': Controller device name
                - 'Class': Device class
                - 'Link policy': Link policy string
                - 'Link mode': Link mode string
                - 'HCI Version': HCI version string with spec info
                - 'LMP Version': LMP version string with spec info
                - 'Manufacturer': Chipset vendor/manufacturer

        Raises:
            RuntimeError: If no interface is specified or if the `hciconfig` command fails.
        """
        if not interface:
            raise RuntimeError("Bluetooth interface must be provided")

        self.interface = interface
        details = {}

        # Ensure interface is up before querying
        #self.run_command(f'hciconfig -a {self.interface} up')
        result = self.run_command(f'hciconfig -a {self.interface}')

        for line in result.stdout.split('\n'):
            line = line.strip()
            if match := re.match('BD Address: (.*) ACL(.*)', line):
                details['BD_ADDR'] = match[1]
            elif match := re.match('Link policy: (.*)', line):
                details['Link policy'] = match[1]
            elif match := re.match('Link mode: (.*)', line):
                details['Link mode'] = match[1]
            elif match := re.match('Name: (.*)', line):
                details['Name'] = match[1]
            elif match := re.match('Class: (.*)', line):
                details['Class'] = match[1]
            elif match := re.match(r'HCI Version: ([^ ]+ \([^)]+\))', line):
                details['HCI Version'] = match[1]
            elif match := re.match(r'LMP Version: ([^ ]+ \([^)]+\))', line):
                details['LMP Version'] = match[1]
            elif match := re.match('Manufacturer: (.*)', line):
                details['Manufacturer'] = match[1]

        # Save as object attributes
        self.name = details.get('Name')
        self.bd_address = details.get('BD_ADDR')
        self.link_policy = details.get('Link policy')
        self.link_mode = details.get('Link mode')
        self.hci_version = details.get('HCI Version')
        self.lmp_version = details.get('LMP Version')
        self.manufacturer = details.get('Manufacturer')

        return details

    def is_adapter_valid(self):
        try:
            self.adapter.GetAll("org.bluez.Adapter1")
            return True
        except dbus.exceptions.DBusException as e:
            self.log.info(f"[WARN] D-Bus Adapter invalid: {e}")
            return False

    def power_on_adapter(self):
        """
        Power on the local Bluetooth adapter.
        """
        adapter = dbus.Interface(
            self.bus.get_object(constants.bluez_service, self.adapter_path),
            constants.props_iface
        )
        adapter.Set(constants.adapter_iface, "Powered", dbus.Boolean(True))

    def inquiry(self, timeout):
        """
        Scan for nearby Bluetooth devices for a specified duration.

        :param timeout: Duration in seconds to scan for devices.
        :return: List of discovered devices in the format "Alias (Address)".
        """
        self.start_discovery()
        time.sleep(timeout)
        self.stop_discovery()

        discovered = []
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"),constants.obj_iface)
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                device_props = dbus.Interface(self.bus.get_object(constants.bluez_service, path),
                                              dbus_interface=constants.props_iface)
                try:
                    address = device_props.Get(constants.device_iface, "Address")
                    alias = device_props.Get(constants.device_iface, "Alias")
                    discovered.append(f"{alias} ({address})")
                except:
                    continue
        return discovered

    def _get_device_path(self, address):
        """
        Format the Bluetooth address to get the BlueZ D-Bus object path.

        :param address: Bluetooth device MAC address.
        :return: D-Bus object path.
        """
        formatted_address = address.replace(":", "_")
        return f"/org/bluez/{self.interface}/dev_{formatted_address}"

    def find_device_path(self, address):
        """
        Find the D-Bus object path of a device by address under the correct adapter.

        :param address: Bluetooth device MAC address.
        :return: D-Bus object path or None if not found.
        """
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
        objects = om.GetManagedObjects()

        formatted_interface_path = f"/org/bluez/{self.interface}/"

        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                if formatted_interface_path in path:  # Make sure it’s under the correct hci
                    props = interfaces[constants.device_iface]
                    if props.get("Address") == address:
                        return path
        return None

    def connect(self, address):
        """
        Establish a BR/EDR connection to the specified Bluetooth device.

        :param address: Bluetooth device MAC address.
        :return: True if connected, False otherwise.
        """
        device_path = self.find_device_path(address)
        if device_path:
            try:
                device = dbus.Interface(
                    self.bus.get_object(constants.bluez_service, device_path),
                    dbus_interface=constants.device_iface
                )
                device.Connect()

                props = dbus.Interface(
                    self.bus.get_object(constants.bluez_service, device_path),
                    constants.props_iface
                )
                connected = props.Get(constants.device_iface, "Connected")
                if connected:
                    self.log.info(f" Connection successful to {address}")
                    return True
                else:
                    self.log.info(f" Connection attempted but not confirmed for {address}")
                    return False

            except Exception as e:
                self.log.info(f" Connection failed: {e}")
                return False
        else:
            self.log.info(f" Device path not found for address {address}")
            return False

    def disconnect(self, address):
        """
        Disconnect a Bluetooth LE device from the specified adapter.

        :param address: Bluetooth MAC address of the device.
        :param interface: Adapter name (e.g., 'hci0') the device is connected to.
        :return: True if disconnected or already disconnected, False if an error occurred.
        """
        device_path = self.find_device_path(address)
        if device_path:
            try:
                device = dbus.Interface(self.bus.get_object(constants.bluez_service, device_path), constants.device_iface)
                props = dbus.Interface(self.bus.get_object(constants.bluez_service, device_path), constants.props_iface)
                connected = props.Get(constants.device_iface, "Connected")
                if not connected:
                    self.log.info(f"Device {address} is already disconnected.")
                    return True
                device.Disconnect()
                return True
            except dbus.exceptions.DBusException as e:
                self.log.info(f"Error disconnecting device {address}: {e}")
        return False

    def remove_device(self, address):
        """
        Removes a paired or known Bluetooth device from the system using BlueZ D-Bus.

        Args:
            address (str): The Bluetooth MAC address of the device to remove.

        Returns:
            bool: True if the device was removed successfully or already not present,
                  False if the removal failed or the device still exists afterward.
        """
        try:
            obj = self.bus.get_object(constants.bluez_service, "/")
            manager = dbus.Interface(obj, constants.obj_iface)
            objects = manager.GetManagedObjects()

            target_path = None
            for path, interfaces in objects.items():
                if constants.device_iface in interfaces:
                    if interfaces[constants.device_iface].get("Address") == address and path.startswith(
                            self.adapter_path):
                        target_path = path
                        break

            if not target_path:
                self.log.info(f"Device with address {address} not found on {self.interface}")
                return True  # Already removed

            adapter = dbus.Interface(
                self.bus.get_object(constants.bluez_service, self.adapter_path),
                constants.adapter_iface
            )

            adapter.RemoveDevice(target_path)
            self.log.info(f"Requested removal of device {address} at path {target_path}")

            # Wait and confirm the device was actually removed
            for _ in range(5):  # retry for up to ~2.5 seconds
                time.sleep(0.5)
                objects = manager.GetManagedObjects()
                if target_path not in objects:
                    self.log.info(f"Device {address} removed successfully.")
                    return True

            self.log.error(f"Device {address} still present after attempted removal.")
            return False

        except dbus.exceptions.DBusException as e:
            self.log.error(f"DBusException while removing device {address}: {e}")
            return False

        except Exception as e:
            self.log.error(f"Unexpected error while removing device {address}: {e}")
            return False

    def _get_device_interface(self, device_path):
        """
        Get the org.bluez.Device1 interface for the specified device path.

        :param device_path: D-Bus object path of the device.
        :return: DBus Interface for the device.
        """
        return dbus.Interface(
            self.bus.get_object(constants.bluez_service, device_path),
            constants.device_iface
        )

    def pair(self, address):
        """
        Pairs with a Bluetooth device using the given controller interface.

        :param address: Bluetooth MAC address.
        :param interface: e.g., 'hci0', 'hci1'
        :return: True if successfully paired, False otherwise.
        """
        device_path = self.find_device_path(address)
        if device_path:
            try:
                device = dbus.Interface(self.bus.get_object(constants.bluez_service, device_path),
                                        dbus_interface=constants.device_iface)
                device.Pair()

                # Wait until pairing is confirmed (optional)
                props = dbus.Interface(self.bus.get_object(constants.bluez_service, device_path),
                                       constants.props_iface)
                paired = props.Get(constants.device_iface, "Paired")
                if paired:
                    self.log.info(f"[Bluetooth] Successfully paired with {address} on {self.interface}")
                    return True
                else:
                    self.log.info(f"[Bluetooth] Pairing not confirmed with {address}")
                    return False

            except dbus.exceptions.DBusException as e:
                self.log.info(f"[Bluetooth] Pairing failed with {address} on {self.interface}: {e}")
                return False
        else:
            self.log.info(f"[Bluetooth] Device path not found for {address} on {self.interface}")
            return False

    def set_discoverable_on(self):
        """
        Makes the Bluetooth device discoverable.

        args: None
        return: None
        """
        self.log.info("Setting Bluetooth device to be discoverable...")
        command = f"hciconfig {self.interface} piscan"
        subprocess.run(command, shell=True)
        self.log.info("Bluetooth device is now discoverable.")

    def set_discoverable_off(self):
        """
        Makes the Bluetooth device non-discoverable.

        args: None
        return: None
        """
        self.log.info("Setting Bluetooth device to be non-discoverable...")
        command = f"hciconfig {self.interface} noscan"
        subprocess.run(command, shell=True)
        self.log.info("Bluetooth device is now non-discoverable.")

    def is_device_paired(self, device_address):
        """
        Checks if the specified device is paired.

        Args:
            device_address (str): Bluetooth MAC address.

        Returns:
            bool: True if paired, False otherwise.
        """
        device_path = self.find_device_path(device_address)
        if not device_path:
            return False

        props = dbus.Interface(
            self.bus.get_object(constants.bluez_service, device_path),
            constants.props_iface
        )
        try:
            return props.Get(constants.device_iface, "Paired")
        except dbus.exceptions.DBusException:
            return False

    def is_device_connected(self, device_address):
        """
        Checks if the specified device is connected.

        Args:
            device_address (str): Bluetooth MAC address.

        Returns:
            bool: True if connected, False otherwise.
        """
        device_path = self.find_device_path(device_address)
        if not device_path:
            self.log.info(f"[DEBUG] Device path not found for {device_address} on {self.interface}")
            return False

        try:
            props = dbus.Interface(
                self.bus.get_object(constants.bluez_service, device_path),
                constants.props_iface
            )
            connected = props.Get(constants.device_iface, "Connected")

            # Extra validation: make sure device is under the correct adapter/interface
            if self.interface not in device_path:
                self.log.info(f"[DEBUG] Device path {device_path} does not match interface {self.interface}")
                return False

            return connected

        except dbus.exceptions.DBusException as e:
            self.log.info(f"[DEBUG] DBusException while checking connection: {e}")
            return False

    def sync_available_devices(self):
        """
        Updates the internal device list with currently available devices.

        args: None
        returns: None
        """
        self.devices.clear()
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                props = interfaces[constants.device_iface]
                address = props.get("Address")
                name = props.get("Name", "Unknown")
                uuids = props.get("UUIDs", [])
                connected = props.get("Connected", False)
                if address:
                    self.devices[address] = {
                        "Name": name,
                        "UUIDs": uuids,
                        "Connected": connected,
                    }

    def get_paired_devices(self):
        """
        Retrieves all Bluetooth devices that are currently paired with the system on the specified adapter.

        Returns:
            dict: A dictionary of paired devices

        """
        paired = {}
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                props = interfaces[constants.device_iface]
                if props.get("Paired", False) and props.get("Adapter") == self.adapter_path:
                    address = props.get("Address")
                    name = props.get("Name", "Unknown")
                    paired[address] = name
        return paired

    def get_connected_devices(self):
        """
        Retrieves all currently connected Bluetooth devices for the specified adapter.

        This method queries the BlueZ D-Bus object manager and returns a dictionary
        of devices that are actively connected and match the adapter path.

        Returns:
            dict: A dictionary of connected devices
        """
        connected = {}
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
        objects = om.GetManagedObjects()
        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                props = interfaces[constants.device_iface]
                if props.get("Connected", False) and props.get("Adapter") == self.adapter_path:
                    address = props.get("Address")
                    name = props.get("Name", "Unknown")
                    connected[address] = name
        return connected

    #--------------------OPP FUNCTIONS---------------------#
    def send_file_via_obex(self, device_address, file_path):
        """
        Send a file to a Bluetooth device via OBEX (Object Push Profile).

        args:
            device_address (str): Bluetooth address of the target device (e.g., 'XX:XX:XX:XX:XX:XX').
            file_path (str): Absolute path to the file to send.

        Returns:
            tuple: A tuple of (status, message). Status can be 'complete', 'error', or 'unknown'.
        """
        if not os.path.exists(file_path):
            msg = f"File does not exist: {file_path}"
            self.log.info(msg)
            return "error", msg

        try:
            session_bus = dbus.SessionBus()
            obex_service = constants.obex_service
            manager_obj = session_bus.get_object(obex_service, "/org/bluez/obex")
            manager = dbus.Interface(manager_obj, constants.obex_client)

            # Clean up old session if it exists
            if self.last_session_path:
                try:
                    manager.RemoveSession(self.last_session_path)
                    self.log.info(f"Removed previous session: {self.last_session_path}")
                    time.sleep(1.0)
                except Exception as e:
                    self.log.info(f"Previous session cleanup failed: {e}")

            # Create a new OBEX session
            session_path = manager.CreateSession(device_address, {"Target": dbus.String("opp")})
            session_path = str(session_path)
            self.last_session_path = session_path
            self.log.info(f"Created OBEX session: {session_path}")

            # Push the file
            opp_obj = session_bus.get_object(obex_service, session_path)
            opp = dbus.Interface(opp_obj, constants.obex_obj_push)
            transfer_path = opp.SendFile(file_path)
            transfer_path = str(transfer_path)
            self.log.info(f"Transfer started: {transfer_path}")

            # Monitor transfer status
            transfer_obj = session_bus.get_object(obex_service, transfer_path)
            transfer_props = dbus.Interface(transfer_obj, constants.props_iface)

            status = "unknown"
            for _ in range(40):
                status = str(transfer_props.Get(constants.obex_obj_transfer, "Status"))
                self.log.info(f"Transfer status: {status}")
                if status in ["complete", "error"]:
                    break
                time.sleep(0.5)

            # Always remove session
            try:
                manager.RemoveSession(session_path)
                self.last_session_path = None
                self.log.info("Session removed after transfer.")
            except Exception as e:
                self.log.info(f"Error removing session: {e}")

            return status, f"Transfer finished with status: {status}"

        except Exception as e:
            msg = f"OBEX file send failed: {e}"
            self.log.info(msg)
            return "error", msg

    def start_opp_receiver(self, save_directory="/tmp"):
        """
        Start an OBEX Object Push server to receive files over Bluetooth.

        args:
            save_directory (str): Directory where received files will be stored.

        Returns:
            bool: True if server started successfully, False otherwise.
        """
        try:
            if not os.path.exists(save_directory):
                os.makedirs(save_directory)

            if self.opp_process and self.opp_process.poll() is None:
                self.opp_process.terminate()
                self.opp_process.wait()
                self.log.info("Previous OPP server stopped.")

            self.opp_process = subprocess.Popen([
                "obexpushd",
                "-B",  # Bluetooth
                "-o", save_directory,
                "-n"  # No confirmation prompt
            ])

            self.log.info(f"OPP server started. Receiving files to {save_directory}")
            return True
        except Exception as e:
            self.log.info(f"Error starting OPP server: {e}")
            return False

    def stop_opp_receiver(self):
        """
        Stop the OBEX Object Push server if it's currently running.

        args: None
        returns: None
        """
        if self.opp_process and self.opp_process.poll() is None:
            self.opp_process.terminate()
            self.opp_process.wait()
            self.log.info("OPP server stopped.")

# -----------A2DP FUNCTIONS----------------------------#
    def set_device_address(self, address):
        """
        Sets the current Bluetooth device for media streaming/control.

        Args:
            address (str): Bluetooth MAC address.
        returns:
            None
        """
        self.device_address = address
        self.device_path = self.find_device_path(address)
        self.device_sink = self.get_sink_for_device(address)

    def get_sink_for_device(self, address):
        """
        Finds the PulseAudio sink associated with a Bluetooth device.

        Args:
            address (str): Bluetooth MAC address.

        Returns:
            str | None: Sink name if found, else None.
        """
        try:
            sinks_output = subprocess.check_output(["pactl", "list", "short", "sinks"], text=True)
            address_formatted = address.replace(":", "_").lower()
            for line in sinks_output.splitlines():
                if address_formatted in line.lower():
                    return line.split()[1]
        except Exception as e:
            self.log.info(f"Error getting sink for device: {e}")
        return None

    def is_a2dp_streaming(self) -> bool:
        """
        Check if an A2DP stream is currently active using PulseAudio.

        Returns:
            bool: True if audio is streaming to a Bluetooth A2DP sink, False otherwise.
        """

        try:
            # Get all active sink inputs (audio streams)
            output = subprocess.check_output("pactl list sink-inputs", shell=True, text=True)

            # Check if any sink input is directed to a Bluetooth A2DP sink
            if "bluez_sink" in output:
                return True

            return False

        except subprocess.CalledProcessError:
            # pactl command failed
            return False


    def start_a2dp_stream(self, address, filepath=None):
        """
        Initiates an A2DP audio stream to a Bluetooth device using BlueZ.

        If the device is not already connected, it attempts to connect first.
        Supports optional MP3-to-WAV conversion before streaming using `aplay`.

        Args:
            address (str): Bluetooth MAC address of the target device.
            filepath (str, optional): Path to the audio file to stream. Must be a WAV or MP3 file.
                                          If MP3, it will be converted to WAV automatically.

        Returns:
            str: Status message indicating success, failure, or error reason.
        """
        device_path = self.find_device_path(address)
        self.log.info(device_path)
        if not device_path:
            return "Device not found"
        try:
            # Ensure device_address is stored for stop_a2dp_stream
            self.device_address = address # Store the address of the device being streamed to
            device = dbus.Interface(self.bus.get_object(constants.bluez_service, device_path), constants.device_iface)
            self.log.info(device)
            props = dbus.Interface(self.bus.get_object(constants.bluez_service, device_path), constants.props_iface)
            connected = props.Get(constants.device_iface, "Connected")
            if not connected:
                device.Connect()
                time.sleep(1.5)
            self.log.info(f"[A2DP] Connected to {address}")
            if not filepath:
                return "No audio file specified for streaming"

            # Convert MP3 to WAV if needed
            if filepath.endswith(".mp3"):
                wav_file = "/tmp/temp_audio.wav"
                if not self.convert_mp3_to_wav(filepath, wav_file):
                    return False
                filepath = wav_file

            self.stream_process = subprocess.Popen(
                ["aplay", filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return f"Streaming started with {filepath}"
        except Exception as e:
            return f"A2DP stream error: {str(e)}"


    def convert_mp3_to_wav(self, audio_path, wav_path):
        """
        Convert an MP3 file to WAV format using ffmpeg.

        Args:
            audio_path (str): Path to the MP3 file.
            wav_path (str): Output path for the converted WAV file.

        Returns:
            bool: True if conversion succeeds, False otherwise.
        """
        try:
            subprocess.run(['ffmpeg', '-y', '-i', audio_path, wav_path], check=True)
            return True
        except subprocess.CalledProcessError as e:
            self.log.info(f"Conversion failed [mp3 to wav]: {e}")
            return False

    def stop_a2dp_stream(self):
        """
        Stop the current A2DP audio stream.

        :return: Status message.
        """
        if self.stream_process:
            self.stream_process.terminate()
            self.stream_process = None
            return "A2DP stream stopped"
        return "No active A2DP stream"

    def get_connected_a2dp_source_devices(self):
        """
        Get a list of currently connected A2DP source devices on the given interface.

        Args:
            interface (str): Controller interface like 'hci0' or 'hci1'

        Returns:
            dict: Dictionary of connected A2DP source devices (MAC -> Name)
        """
        connected = {}
        #adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
        objects = om.GetManagedObjects()

        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                props = interfaces[constants.device_iface]
                if props.get("Connected", False) and props.get("Adapter") == self.adapter_path:
                    uuids = props.get("UUIDs", [])
                    if any("110a" in uuid.lower() for uuid in uuids):  # A2DP Source UUID
                        address = props.get("Address")
                        name = props.get("Name", "Unknown")
                        connected[address] = name
        return connected

    def get_connected_a2dp_sink_devices(self):
        """
        Get a list of currently connected A2DP sink devices on the given interface.

        Args:
            interface (str): Controller interface like 'hci0' or 'hci1'

        Returns:
            dict: Dictionary of connected A2DP sink devices (MAC -> Name)
        """
        connected = {}
        #adapter_path = f"/org/bluez/{interface}"
        om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
        objects = om.GetManagedObjects()

        for path, interfaces in objects.items():
            if constants.device_iface in interfaces:
                props = interfaces[constants.device_iface]
                if props.get("Connected", False) and props.get("Adapter") == self.adapter_path:
                    uuids = props.get("UUIDs", [])
                    if any("110b" in uuid.lower() for uuid in uuids):  # A2DP Sink UUID
                        address = props.get("Address")
                        name = props.get("Name", "Unknown")
                        connected[address] = name
        return connected

    def media_control(self, command, address=None):
        """
        Sends AVRCP (Audio/Video Remote Control Profile) media control commands to a connected Bluetooth device.

        Supported commands include: play, pause, next, previous, and rewind.
        This method interacts with the BlueZ `org.bluez.MediaControl1` D-Bus interface.

        Args:
            command (str): The AVRCP command to send. Must be one of: "play", "pause", "next", "previous", "rewind".
            address (str, optional): Bluetooth MAC address of the target device. If None, a default may be used.

        Returns:
            str: Status message indicating success, failure, or invalid command.
        """
        valid = {
            "play": "Play",
            "pause": "Pause",
            "next": "Next",
            "previous": "Previous",
            "rewind": "Rewind"
        }

        if command not in valid:
            return f"Invalid command: {command}"

        control_iface = self._get_media_control_interface(address)

        if not control_iface:
            self.log.info(" MediaControl1 interface NOT FOUND")
            return f"MediaControl1 interface not found for {address}"

        self.log.info(f" MediaControl1 interface FOUND")

        try:
            getattr(control_iface, valid[command])()
            return f"AVRCP {command} sent to {address}"
        except Exception as e:
            return f"Error sending AVRCP {command}: {str(e)}"

    def _get_media_control_interface(self, address):
        """
        Internal helper method to retrieve the `org.bluez.MediaControl1` D-Bus interface for a given Bluetooth device.

        Args:
            address (str): The MAC address of the target Bluetooth device.

        Returns:
            dbus.Interface or None: The MediaControl1 D-Bus interface if found, otherwise None.
           """
        try:
            om = dbus.Interface(self.bus.get_object(constants.bluez_service, "/"), constants.obj_iface)
            objects = om.GetManagedObjects()
            formatted_addr = address.replace(":", "_").upper()


            controller_path = self.adapter_path  # fallback to stored adapter

            for path, interfaces in objects.items():
                if constants.media_iface in interfaces:
                    if formatted_addr in path and path.startswith(controller_path):
                        self.log.info(f" Found MediaControl1 at {path}")
                        return dbus.Interface(
                            self.bus.get_object(constants.bluez_service, path),
                            constants.media_iface
                        )

            self.log.info(f" No MediaControl1 interface found for {address} under {controller_path}")
        except Exception as e:
            self.log.info(f" Exception while getting MediaControl1 interface: {e}")
        return None
