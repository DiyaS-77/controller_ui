import os
import dbus
import re
import time
import constants


from PyQt6.QtCore import QTimer, QFileSystemWatcher
from PyQt6.QtGui import QFont
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QListWidgetItem, QGroupBox, QDialog, QHeaderView, QSizePolicy
from PyQt6.QtWidgets import QGridLayout
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QListWidget
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QLineEdit
from PyQt6.QtWidgets import QPushButton
from PyQt6.QtWidgets import QTableWidget
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtWidgets import QTextBrowser
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QFormLayout
from PyQt6.QtWidgets import QTextEdit
from PyQt6.QtWidgets import QTabWidget
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtWidgets import QFileDialog


from logger import Logger
from Backend_lib.Linux.bluez import BluetoothDeviceManager


class Controller:
    """
    Represents the local Bluetooth controller.

    Stores HCI version, manufacturer details, address, and link policies.
    """

    def __init__(self):
        self.name = None
        self.bd_address = None
        self.link_mode = None
        self.link_policy = None
        self.hci_version = None
        self.lmp_version = None
        self.manufacturer = None




class TestApplication(QWidget):
    """
    Main GUI class for the Bluetooth Test Host.

    Handles Bluetooth discovery, pairing, connection (BR/EDR & LE), A2DP streaming,
    and media control operations using BlueZ and PulseAudio.
    """

    def __init__(self,interface=None, back_callback=None,log_path=None):
        """
        Initialize the TestApplication widget.

        Args:
            interface (str): Bluetooth adapter interface (e.g., hci0).
            bluetooth_device_manager: An instance of BluetoothDeviceManager class .
            back_callback (callable): Optional callback to trigger on back action.

        returns:
            None
        """
        super().__init__()
        self.interface = interface
        self.log = Logger("UI")
        self.discovery_active = False
        self.back_callback = back_callback
        self.controller = Controller()
        self.bluetooth_device_manager = BluetoothDeviceManager.get_instance(
            capability="NoInputNoOutput",
            log_path=log_path
        )
        self.bluetooth_device_manager.initialize_adapter(self.interface)
        self.test_application_clicked()


    def load_connected_devices(self):
        """
        Loads and displays all paired and currently connected Bluetooth devices
        into the profiles list widget.

        args: None
        returns: None
        """
        self.paired_devices={}
        self.connected_devices={}
        gap_index = self.profiles_list_widget.count() - 1
        self.paired_devices = self.bluetooth_device_manager.get_paired_devices()
        self.connected_devices = self.bluetooth_device_manager.get_connected_devices()

        # Use a set to avoid duplicates
        unique_devices = set(self.paired_devices.keys()).union(self.connected_devices.keys())

        for device_address in unique_devices:
            device_name = self.bluetooth_device_manager.get_device_name(device_address)
            display_text = f"{device_address} ({device_name})" if device_name else device_address

            device_item = QListWidgetItem(display_text)
            device_item.setFont(QFont("Arial", 10))
            device_item.setForeground(Qt.GlobalColor.black)
            gap_index += 1
            self.profiles_list_widget.insertItem(gap_index, device_item)

    def is_bluetooth_address(self, text):
        pattern = r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$"
        return re.match(pattern, text) is not None

    def profile_selected(self, profile_name=None):
            """
            Handles profile selection from either the list or a button.

            Args:
                profile_name (str): Optional. If provided, used instead of list selection.
            """
            if profile_name is None:
                selected_item = self.profiles_list_widget.currentItem()
                if not selected_item:
                    return
                selected_item_text = selected_item.text()
            else:
                selected_item_text = profile_name
            bold_font = QFont()
            bold_font.setBold(True)

            # Remove old UI
            if hasattr(self, 'profile_methods_widget'):
                self.profile_methods_widget.deleteLater()

            addr_only = selected_item_text.split()[0]
            if self.is_bluetooth_address(addr_only):
                self.load_profile_tabs_for_device(addr_only)
                QTimer.singleShot(0, lambda: self.on_profile_tab_changed(self.device_tab_widget.currentIndex()))
                return

            if selected_item_text == "GAP":
                bold_font = QFont()
                bold_font.setBold(True)
                self.profile_description_text_browser.clear()
                self.profile_description_text_browser.append("GAP Profile Selected")
                self.profile_description_text_browser.setFont(bold_font)
                self.profile_description_text_browser.append("Use the below methods as required:")


    def test_application_clicked(self):
        """
           Create and display the main testing application GUI.

           This interface consists of:
           - A profile selection list
           - Bluetooth controller details
           - A text browser showing methods related to selected profile
           - Three log viewers: Bluetoothd, PulseAudio, and HCI Dump
           - A back button to return to the previous window

           args: None
           returns: None
           """

        # Create the main grid
        self.main_grid_layout = QGridLayout()

        # Grid 1 Up : List of Profiles
        bold_font = QFont()
        bold_font.setBold(True)
        self.profiles_list_widget = QListWidget()
        self.profiles_list_label = QLabel("Paired devices:")
        self.profiles_list_label.setFont(bold_font)
        self.profiles_list_label.setStyleSheet("color:black")
        self.main_grid_layout.addWidget(self.profiles_list_label, 0, 0)
        self.gap_button = QPushButton("GAP")
        self.gap_button.setFont(bold_font)
        self.gap_button.setStyleSheet("color: black; background-color: lightblue;")
        self.gap_button.setMinimumWidth(120)
        self.gap_button.setMinimumHeight(30)
        self.gap_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.gap_button.clicked.connect(lambda: self.profile_selected("GAP"))
        header_layout = QHBoxLayout()
        header_layout.addWidget(self.profiles_list_label)
        header_layout.addSpacing(20)  # add 20px space between label and button
        header_layout.addWidget(self.gap_button)
        header_layout.addStretch()

        self.main_grid_layout.addLayout(header_layout, 0, 0, 1, 2)

        self.profiles_list_widget.setFont(bold_font)
        self.profiles_list_widget.setStyleSheet("border: 2px solid black;" "color: black;" "background: transparent;")
        self.profiles_list_widget.itemSelectionChanged.connect(lambda: self.profile_selected())

        self.profiles_list_widget.setFixedWidth(350)
        self.main_grid_layout.addWidget(self.profiles_list_widget, 1, 0, 2, 2)


        controller_details_widget = QWidget()
        controller_details_layout = QVBoxLayout()
        controller_details_widget.setStyleSheet("color: blue;")
        controller_details_widget.setFont(bold_font)
        controller_details_widget.setStyleSheet("border: 2px solid black;" "color: black;" "background: transparent;")
        self.main_grid_layout.addWidget(controller_details_widget, 3, 0, 8, 2)
        controller_details_layout.setContentsMargins(0, 0, 0, 0)
        controller_details_layout.setSpacing(0)

        self.bluetooth_device_manager.get_controller_details(interface=self.interface)

        self.controller.name = self.bluetooth_device_manager.name
        self.controller.bd_address = self.bluetooth_device_manager.bd_address
        self.controller.link_policy = self.bluetooth_device_manager.link_policy
        self.controller.lmp_version = self.bluetooth_device_manager.lmp_version
        self.controller.link_mode = self.bluetooth_device_manager.link_mode
        self.controller.hci_version = self.bluetooth_device_manager.hci_version
        self.controller.manufacturer = self.bluetooth_device_manager.manufacturer

        controller_details_label = QLabel("Controller Details:")

        controller_details_label.setFont(bold_font)
        controller_details_layout.addWidget(controller_details_label)

        # Controller Name
        controller_name_layout = QHBoxLayout()
        controller_name_label = QLabel("Controller Name:")
        controller_name_label.setFont(bold_font)
        controller_name_label.setStyleSheet("""
                       border-top: 0px solid black;
                       border-right: 1px solid black;
                       border-bottom: 0px solid black;
                   """)
        controller_name_layout.addWidget(controller_name_label)
        controller_name_text = QLabel(self.bluetooth_device_manager.name)
        controller_name_text.setStyleSheet("""
                       border-top: 0px solid black;
                       border-left: 1px solid black;
                       border-bottom: 0px solid black;
                   """)
        controller_name_layout.addWidget(controller_name_text)
        controller_details_layout.addLayout(controller_name_layout)

        # Controller Address
        controller_address_layout = QHBoxLayout()
        controller_address_label = QLabel("Controller Address:")
        controller_address_label.setFont(bold_font)
        controller_address_label.setStyleSheet("""
                       border-right: 1px solid black;
                       border-bottom: 0px solid black;
                   """)
        controller_address_layout.addWidget(controller_address_label)
        controller_address_text = QLabel(self.bluetooth_device_manager.bd_address)
        controller_address_text.setStyleSheet("""
                       border-left: 1px solid black; 
                       border-bottom: 0px solid black;
                   """)
        controller_address_layout.addWidget(controller_address_text)
        controller_details_layout.addLayout(controller_address_layout)

        # Link Mode
        controller_link_mode_layout = QHBoxLayout()
        controller_link_mode_label = QLabel("Link Mode:")
        controller_link_mode_label.setFont(bold_font)
        controller_link_mode_label.setStyleSheet("""
                       border-right: 1px solid black;
                       border-bottom: 0px solid black;
                   """)
        controller_link_mode_layout.addWidget(controller_link_mode_label)
        controller_link_mode_text = QLabel(self.bluetooth_device_manager.link_mode)
        controller_link_mode_text.setStyleSheet("""
                       border-left: 1px solid black;  
                       border-bottom: 0px solid black;
                   """)
        controller_link_mode_layout.addWidget(controller_link_mode_text)
        controller_details_layout.addLayout(controller_link_mode_layout)

        # Link Policy
        controller_link_policy_layout = QHBoxLayout()
        controller_link_policy_label = QLabel("Link Policy:")
        controller_link_policy_label.setFont(bold_font)
        controller_link_policy_label.setStyleSheet("""
                border-right: 1px solid black;
                border-bottom: 0px solid black;
            """)
        controller_link_policy_layout.addWidget(controller_link_policy_label)
        controller_link_policy_text = QLabel(self.bluetooth_device_manager.link_policy)
        controller_link_policy_text.setStyleSheet("""  
                border-left: 1px solid black;
                border-bottom: 0px solid black;
            """)
        controller_link_policy_layout.addWidget(controller_link_policy_text)
        controller_details_layout.addLayout(controller_link_policy_layout)

        # HCI Version
        controller_hci_version_layout = QHBoxLayout()
        controller_hci_version_label = QLabel("HCI Version:")
        controller_hci_version_label.setFont(bold_font)
        controller_hci_version_label.setStyleSheet("""
                        border-right: 1px solid black;
                        border-bottom: 0px solid black;
                    """)
        controller_hci_version_layout.addWidget(controller_hci_version_label)
        controller_hci_version_text = QLabel(self.bluetooth_device_manager.hci_version)
        controller_hci_version_text.setStyleSheet("""
                        border-left: 1px solid black; 
                        border-bottom: 0px solid black;
                    """)
        controller_hci_version_layout.addWidget(controller_hci_version_text)
        controller_details_layout.addLayout(controller_hci_version_layout)

        # LMP Version
        controller_lmp_version_layout = QHBoxLayout()
        controller_lmp_version_label = QLabel("LMP Version:")
        controller_lmp_version_label.setFont(bold_font)
        controller_lmp_version_label.setStyleSheet("""
                border-right: 1px solid black;
                border-bottom: 0px solid black;
            """)
        controller_lmp_version_layout.addWidget(controller_lmp_version_label)
        controller_lmp_version_text = QLabel(self.bluetooth_device_manager.lmp_version)
        controller_lmp_version_text.setStyleSheet(""" 
                       border-left: 1px solid black;
                       border-bottom: 0px solid black;
                   """)
        controller_lmp_version_layout.addWidget(controller_lmp_version_text)
        controller_details_layout.addLayout(controller_lmp_version_layout)

        # Manufacturer
        controller_manufacturer_layout = QHBoxLayout()
        controller_manufacturer_label = QLabel("Manufacturer:")
        controller_manufacturer_label.setFont(bold_font)
        controller_manufacturer_label.setFixedWidth(350)
        controller_manufacturer_layout.addWidget(controller_manufacturer_label)
        controller_manufacturer_text = QLabel(self.bluetooth_device_manager.manufacturer)
        controller_manufacturer_layout.addWidget(controller_manufacturer_text)
        controller_details_layout.addLayout(controller_manufacturer_layout)

        # Setting the controller details widget with fixedwidth being mentioned
        controller_details_widget.setLayout(controller_details_layout)
        controller_details_widget.setFixedWidth(350)

        # Grid2: Profile description
        profile_description_label = QLabel("Profile Methods or Procedures:")
        profile_description_label.setFont(bold_font)
        profile_description_label.setStyleSheet("color: black;")

        self.main_grid_layout.addWidget(profile_description_label, 0, 2)
        self.profile_description_text_browser = QTextBrowser()
        self.main_grid_layout.addWidget(self.profile_description_text_browser, 1, 2, 10, 2)
        self.profile_description_text_browser.setStyleSheet(
            "background: transparent;color:black;border: 2px solid black;")
        self.profile_description_text_browser.setFixedWidth(500)

        # Grid3: HCI Dump Logs
        dump_logs_label = QLabel("Dump Logs:")
        dump_logs_label.setFont(bold_font)
        dump_logs_label.setStyleSheet("color: black;")
        self.main_grid_layout.addWidget(dump_logs_label, 0, 4)
        self.dump_logs_text_browser = QTabWidget()
        self.main_grid_layout.addWidget(self.dump_logs_text_browser, 1, 4, 10, 2)
        self.dump_logs_text_browser.setStyleSheet("""
            QTabWidget::pane {
                background: transparent;
                border: 2px solid black;
                margin-top: 8px; 

            }
            QTabBar::tab {
                background: transparent;
                color: black;
                border-top: 2px solid black;
                border-bottom: 2px solid black;
                border-left: 2px solid black;
                border-right: none;
                padding: 7px;
                height: 20px;  /* Fixed tab height */
            }

            QTabBar::tab:last {
            border-right: 2px solid black;  /* Add right border to last tab only */
            }
        """)

        tab_bar = self.dump_logs_text_browser.tabBar()
        tab_bar.setUsesScrollButtons(False)
        tab_bar.setExpanding(True)
        self.dump_logs_text_browser.setFixedWidth(400)


        back_button = QPushButton("Back")
        back_button.setFixedSize(100, 40)
        back_button.setStyleSheet("""
            QPushButton {
                font-size: 16px;
                padding: 6px;
                background-color: black;
                color: white;
                border: 2px solid gray;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #333333;
            }
        """)

        back_button.clicked.connect(lambda: self.back_callback())
        back_button_layout = QHBoxLayout()
        back_button_layout.addWidget(back_button)
        back_button_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.main_grid_layout.addLayout(back_button_layout, 999, 5)

        self.setLayout(self.main_grid_layout)
        QTimer.singleShot(1000, self.load_connected_devices)

