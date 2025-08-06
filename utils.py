import socket
import subprocess
import re
import os
import constants
import time


from Backend_lib.Linux import hci_commands as hci


class Result:

    """
    Class of result attributes of an executed command.

    Attributes:
        command: command to be executed.
        exit_status: command's exit status.
        stdout: command's output.
        stderr: command's error.
    """
    def __init__(self, command, stdout, stderr, pid, exit_status):
        self.command = command
        self.stdout = stdout
        self.stderr = stderr
        self.pid = pid
        self.exit_status = exit_status

    def __repr__(self):
        return ('Result(command = %r, stdout = %r, stderr = %r, exit_status = %r)'
                ) % (self.command, self.stdout, self.stderr, self.exit_status)


def run(log, command, logfile=None, subprocess_input=""):
    """
    Executes a command in a subprocess and returns its process id, output,
    error and exit status.

    This function will block until the subprocess finishes or times out.

    Args:
        log: logger instance for capturing logs
        command: command to be executed.
        logfile: command output logfile path.
        subprocess_input: Input to be given for the subprocess.

    Returns:
        result: result object of executed command, False on error.
    """
    if logfile:
        proc = subprocess.Popen(command, stdout=open(logfile, 'w+'), stderr=open(logfile, 'w+'), stdin=subprocess.PIPE,
                                shell=True)
        return proc
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, shell=True)

    (out, err) = proc.communicate(timeout=600, input=subprocess_input.encode())

    result = Result(command=command, stdout=out.decode("utf-8").strip(), stderr=err.decode("utf-8").strip(),
                    pid=proc.pid, exit_status=proc.returncode)
    output = out.decode("utf-8").strip() if out else err.decode("utf-8").strip()
    log.info("Command: {}\nOutput: {}".format(command, output))
    return result


def get_controllers_connected(log):
    """
        Returns the list of controllers connected to the host.

        args : None
        Returns:
            dict: Dictionary with BD address as key and interface as value.
    """
    controllers_list = {}
    result = run(log, 'hciconfig -a | grep -B 2 \"BD A\"')
    result = result.stdout.split("--")
    if result[0]:
        for res in result:
            res = res.strip("\n").replace('\n', '')
            if match := re.match('(.*):	Type:.+BD Address: (.*) ACL(.*)', res):
                controllers_list[match[2]] = match[1]
        log.info("Controllers {} found on host".format(controllers_list))
    return controllers_list


def get_controller_interface_details(log, controllers_list, bd_address):

    """
        Gets the controller's interface and bus details.

        args: None

        Returns:
            str: Interface and Bus information.
        """
    interface = controllers_list[bd_address]
    result = run(log, f"hciconfig -a {interface} | grep Bus")
    return f"Interface: {interface} \t Bus: {result.stdout.split('Bus:')[1].strip()}"


def start_dump_logs(interface, log, log_path):
    """
      Stops the hcidump logging process, if running.

      Args:
          log (Logger): Logger instance used for logging.
          interface (str): The Bluetooth interface to stop logging for.
          log_path : log file path

      Returns:
          bool: True if the process was stopped or not running, False if an error occurred.
      """
    try:
        if not interface:
            log.info("[ERROR] Interface is not provided for hcidump")
            return False

        subprocess.run(
            constants.hciconfig_up_command.format(interface=interface).split(),
            capture_output=True
        )

        hcidump_log_name = os.path.join(log_path, f"{interface}_hcidump.log")
        log.info(f"[INFO] Starting hcidump: {constants.hcidump_command}")

        hcidump_process = subprocess.Popen(
            constants.hcidump_command.format(interface=interface).split(),
            stdout=open(hcidump_log_name, 'a+'),
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True
        )

        log.info(f"[INFO] hcidump process started: {hcidump_log_name}")
        return hcidump_log_name

    except Exception as e:
        log.info(f"[ERROR] Failed to start hcidump: {e}")
        return False


def convert_to_little_endian(num, num_of_octets):
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


def run_hci_cmd(ogf, command, interface, log, parameters):
    """
    Executes an HCI command with provided parameters.

    Args:
        ogf (str): Opcode Group Field (e.g., '0x03').
        command (str): Specific HCI command name.
        interface (str): The Bluetooth interface (e.g., 'hci0') on which to run the command.
        log (Logger): Logger instance used for logging output and errors.
        parameters (list): List of parameters for the command.

    Returns:
        subprocess.CompletedProcess: Result of command execution.
    """
    _ogf = ogf.lower().replace(' ', '_')
    _ocf_info = getattr(hci, _ogf)[command]
    hci_command = 'hcitool -i {} cmd {} {}'.format(interface, hci.hci_commands[ogf], _ocf_info[0])

    for index in range(len(parameters)):
        param_len = list(_ocf_info[1][index].values())[1] if len(
            _ocf_info[1][index].values()) > 1 else None
        if param_len:
            parameter = convert_to_little_endian(parameters[index], param_len)
        else:
            parameter = parameters[index].replace('0x', '')
        hci_command = ' '.join([hci_command, parameter])
    log.info(f"Executing command: {hci_command}")
    return run(log, hci_command)

def keep_l2cap_connection_alive(log, bd_addr):
    try:
        log.info(f"[INFO] Connecting L2CAP to {bd_addr}")
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
        time.sleep(1)
        sock.connect((bd_addr, 0x0001))  # Connect to SDP

        log.info(f"[INFO] L2CAP connection active with {bd_addr}")
        while True:
            time.sleep(1)  # Keep the socket alive

    except Exception as e:
        log.error(f"[ERROR] L2CAP connection error: {e}")


def get_connection_handles(log, interface):
    """
    Retrieves active Bluetooth connection handles for the current interface.

    args: None
    Returns:
        dict: Dictionary of connection handles with hex values.
    """
    hcitool_con_cmd = f"hcitool -i {interface} con"
    handles = {}
    result = run(log, hcitool_con_cmd)
    results = result.stdout.split('\n')
    for line in results:
        if 'handle' in line:
            handle = (line.strip().split('state')[0]).replace('< ', '').strip()
            handles[handle] = hex(int(handle.split(' ')[-1]))
    return handles


def stop_dump_logs(log, interface):
    """
    Stops the hcidump logging process, if running.

    Returns:
        bool: True if the process was stopped or not running, False if an error occurred.
    """
    hcidump_process = None
    log.info("[INFO] Stopping HCI dump logs")
    if hcidump_process:
        try:
            hcidump_process.terminate()
            hcidump_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            hcidump_process.kill()
            hcidump_process.wait()
        hcidump_process = None

    if interface:
        try:
            result = subprocess.run(['pgrep', '-f', f'hcidump.*{interface}'],
                                    capture_output=True, text=True)
            if result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    subprocess.run(['kill', '-TERM', pid], stderr=subprocess.DEVNULL)
                    time.sleep(1)
                for pid in pids:
                    subprocess.run(['kill', '-KILL', pid], stderr=subprocess.DEVNULL)
        except Exception as e:
            log.info(f"[ERROR] Error killing hcidump: {e}")
            return False

    log.info("[INFO] HCI dump logs stopped successfully")
    return True
