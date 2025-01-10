from view.widgets.base_device_widget import BaseDeviceWidget, create_widget, scan_for_properties
from qtpy.QtWidgets import QPushButton, QStyle, QWidget, QVBoxLayout, QFrame, QSizePolicy
from qtpy.QtCore import Qt


class CameraWidget(BaseDeviceWidget):

    def __init__(self, camera, advanced_user: bool = True):
        """Modify BaseDeviceWidget to be specifically for camera. Main need are adding roi validator,
        live view button, and snapshot button.
        :param camera: camera object
        :param advanced_user: boolean specifying complexity of widget. If True, all property widget of camera will be
        hidden and only the snapshot and live button will be shown.
        """

        self.camera_properties = scan_for_properties(camera)
        del self.camera_properties["latest_frame"]  # remove image property

        super().__init__(type(camera), self.camera_properties)

        if not advanced_user:  # hide widgets
            for widget in self.property_widgets.values():
                widget.setVisible(False)

        # create and format livestream button and snapshot button
        self.live_button = self.create_live_button()
        self.snapshot_button = self.create_snapshot_button()
        self.alignment_button = self.create_alignment_button()
        self.crosshairs_button = self.create_crosshairs_button()
        combobox_pixel_type = self.property_widgets["pixel_type"].layout().itemAt(1).widget()
        combobox_pixel_type_label = self.property_widgets["pixel_type"].layout().itemAt(0).widget()
        combobox_pixel_type_label.setVisible(False)  # hide power_mw label
        picture_buttons = create_widget(
            "H",
            self.live_button,
            self.snapshot_button,
            self.alignment_button,
            self.crosshairs_button,
            combobox_pixel_type,
        )

        if advanced_user:  # Format widgets better in advaced user mode

            _ = QWidget()  # dummy widget
            direct = Qt.FindDirectChildrenOnly

            # reformat timing widgets

            timing_widgets = create_widget(
                "VH",
                *self.property_widgets.get("exposure_time_ms", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("frame_time_ms", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("line_interval_us", _).findChildren(QWidget, options=direct),
            )
            # check if properties have setters and if not, disable widgets
            for i, prop in enumerate(["exposure_time_ms", "frame_time_ms", "line_interval_us"]):
                attr = getattr(type(camera), prop, False)
                if getattr(attr, "fset", None) is None:
                    timing_widgets.children()[i + 1].setEnabled(False)

            # reformat sensor width widget
            width_widget = create_widget(
                "HV",
                *self.property_widgets.get("width_px", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("width_offset_px", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("sensor_width_px", _).findChildren(QWidget, options=direct),
            )

            # check if properties have setters and if not, disable widgets
            for i, prop in enumerate(["width_px", "width_offset_px", "sensor_width_px"]):
                attr = getattr(type(camera), prop, False)
                if getattr(attr, "fset", None) is None:
                    width_widget.children()[i + 1].setEnabled(False)

            # reformat sensor height widget
            height_widget = create_widget(
                "HV",
                *self.property_widgets.get("height_px", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("height_offset_px", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("sensor_height_px", _).findChildren(QWidget, options=direct),
            )

            # check if properties have setters and if not, disable widgets
            for i, prop in enumerate(["height_px", "height_offset_px", "sensor_height_px"]):
                attr = getattr(type(camera), prop, False)
                if getattr(attr, "fset", None) is None:
                    height_widget.children()[i + 1].setEnabled(False)

            # combine timing, width, and height widgets
            roi_widget = create_widget("H", width_widget, height_widget)
            combined_widget = create_widget("V", timing_widgets, roi_widget)
            layout = QVBoxLayout()
            layout.addWidget(combined_widget)

            # frame = QFrame()
            # frame.setLayout(layout)
            # frame.setStyleSheet(f".QFrame {{ border:4px solid green; background-color: gray}} ")
            # frame.setFrameStyle(QFrame.Sunken)
            # # frame.setFrameStyle(24)

            # reformat pixel options widgets
            pixel_widgets = create_widget(
                "HV",
                *self.property_widgets.get("binning", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("bit_packing_mode", _).findChildren(QWidget, options=direct),
                *self.property_widgets.get("readout_mode", _).findChildren(QWidget, options=direct),
            )

            # check if properties have setters and if not, disable widgets. Have to do it inside pixel widget
            for i, prop in enumerate(["binning", "bit_packing_mode", "readout_mode"]):
                attr = getattr(type(camera), prop)
                if getattr(attr, "fset", None) is None:
                    pixel_widgets.children()[i + 1].setEnabled(False)

            # reformat trigger widget
            trigger_widget_label = self.property_widgets["trigger"].layout().itemAt(0).widget()
            trigger_widget_label.setVisible(False)  # hide power_mw label
            trigger_widget = self.property_widgets["trigger"].layout().itemAt(1).widget()
            trigger_mode_widget = trigger_widget.layout().itemAt(0)
            trigger_mode_widget.widget().layout().itemAt(0).widget().setText("Trigger Mode")
            trigger_source_widget = trigger_widget.layout().itemAt(1)
            trigger_source_widget.widget().layout().itemAt(0).widget().setText("Trigger Source")
            trigger_polarity_widget = trigger_widget.layout().itemAt(2)
            trigger_polarity_widget.widget().layout().itemAt(0).widget().setText("Trigger Polarity")

            trigger_widget = create_widget(
                "V", trigger_mode_widget.widget(), trigger_source_widget.widget(), trigger_polarity_widget.widget()
            )

            # reformat pixel trigger widget
            pixel_trigger_widget = create_widget("H", pixel_widgets, trigger_widget)

            # reformat temperature widgets
            sensor_temperature_c = self.property_widgets["sensor_temperature_c"].layout().itemAt(1).widget()
            sensor_temperature_c.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            sensor_temperature_c.setMinimumWidth(40)
            sensor_temperature_c.setMaximumWidth(40)

            textbox_mainboard_temperature_c = (
                self.property_widgets["mainboard_temperature_c"].layout().itemAt(1).widget()
            )
            textbox_mainboard_temperature_c.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
            textbox_mainboard_temperature_c.setMinimumWidth(40)
            textbox_mainboard_temperature_c.setMaximumWidth(40)

            temperature_widget = create_widget(
                "H", self.property_widgets["sensor_temperature_c"], self.property_widgets["mainboard_temperature_c"]
            )

            central_widget = self.centralWidget()
            central_widget.layout().setSpacing(0)  # remove space between central widget and newly formatted widgets
            self.setCentralWidget(
                create_widget(
                    "V", picture_buttons, combined_widget, pixel_trigger_widget, temperature_widget, central_widget
                )
            )
        else:  # add snapshot button and liveview
            central_widget = self.centralWidget()
            central_widget.layout().setSpacing(0)  # remove space between central widget and newly formatted widgets
            self.setCentralWidget(create_widget("H", self.live_button, self.snapshot_button))

        # check if frame_time_ms_widget exits and its has a validator
        if hasattr(self, "frame_time_ms_widget") and self.frame_time_ms_widget.validator() is not None:
            self.frame_time_ms_widget.validator().setDecimals(2)  # set frame time decimals to 2
        if hasattr(self, "exposure_time_ms_widget") and self.exposure_time_ms_widget.validator() is not None:
            self.exposure_time_ms_widget.validator().setDecimals(2)  # set exposure time decimals to 2

    def create_live_button(self) -> QPushButton:
        """Add live button"""

        button = QPushButton("Live")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        button.setIcon(icon)

        return button

    def create_snapshot_button(self) -> QPushButton:
        """Add snapshot button"""

        button = QPushButton("Snapshot")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        button.setIcon(icon)
        return button

    def create_alignment_button(self) -> QPushButton:
        """Add alignment button"""

        button = QPushButton("Alignment")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton)
        button.setIcon(icon)
        return button

    def create_crosshairs_button(self) -> QPushButton:
        """Add edges button"""

        button = QPushButton("Crosshair")
        icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DockWidgetCloseButton)
        button.setIcon(icon)
        return button


# from view.widgets.device_widgets.camera_widget import CameraWidget
# from view.widgets.base_device_widget import BaseDeviceWidget, create_widget, scan_for_properties
# from qtpy.QtWidgets import QPushButton, QStyle, QWidget, QCheckBox
# from qtpy.QtCore import Qt


# class ExaSPIMCameraWidget(BaseDeviceWidget):

#     def __init__(self, camera, advanced_user: bool = True):
#         """Modify CameraWidget to be specific for ExaSPIM.
#         :param camera: camera object
#         :param advanced_user: boolean specifying complexity of widget. If True, all property widget of camera will be
#         hidden and only the snapshot and live button will be shown.
#         """

#         self.camera_properties = scan_for_properties(camera)
#         del self.camera_properties["latest_frame"]  # remove image property

#         super().__init__(type(camera), self.camera_properties)

#         if not advanced_user:  # hide widgets
#             for widget in self.property_widgets.values():
#                 widget.setVisible(False)

#         # create and format livestream button and snapshot button
#         self.live_button = self.create_live_button()
#         self.snapshot_button = self.create_snapshot_button()
#         self.alignment_button = self.create_alignment_button()
#         self.crosshairs_button = self.create_crosshairs_button()
#         picture_buttons = create_widget(
#             "H", self.live_button, self.snapshot_button, self.alignment_button, self.crosshairs_button
#         )

#         if advanced_user:  # Format widgets better in advaced user mode

#             _ = QWidget()  # dummy widget
#             direct = Qt.FindDirectChildrenOnly

#             # reformat binning and pixel type
#             pixel_widgets = create_widget(
#                 "VH",
#                 *self.property_widgets.get("binning", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("pixel_type", _).findChildren(QWidget, options=direct),
#             )
#             # check if properties have setters and if not, disable widgets. Have to do it inside pixel widget
#             for i, prop in enumerate(["binning", "pixel_type"]):
#                 attr = getattr(type(camera), prop)
#                 if getattr(attr, "fset", None) is None:
#                     pixel_widgets.children()[i + 1].setEnabled(False)

#             # reformat timing widgets
#             timing_widgets = create_widget(
#                 "VH",
#                 *self.property_widgets.get("exposure_time_ms", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("frame_time_ms", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("line_interval_us", _).findChildren(QWidget, options=direct),
#             )
#             # check if properties have setters and if not, disable widgets
#             for i, prop in enumerate(["exposure_time_ms", "frame_time_ms", "line_interval_us"]):
#                 attr = getattr(type(camera), prop, False)
#                 if getattr(attr, "fset", None) is None:
#                     timing_widgets.children()[i + 1].setEnabled(False)

#             # reformat sensor height and width widget
#             sensor_size_widget = create_widget(
#                 "VH",
#                 *self.property_widgets.get("sensor_width_px", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("sensor_height_px", _).findChildren(QWidget, options=direct),
#             )
#             # check if properties have setters and if not, disable widgets
#             for i, prop in enumerate(["sensor_width_px", "sensor_height_px"]):
#                 attr = getattr(type(camera), prop, False)
#                 if getattr(attr, "fset", None) is None:
#                     sensor_size_widget.children()[i + 1].setEnabled(False)

#             # reformat roi widget
#             self.roi_widget = create_widget(
#                 "VH",
#                 *self.property_widgets.get("width_px", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("width_offset_px", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("height_px", _).findChildren(QWidget, options=direct),
#                 *self.property_widgets.get("height_offset_px", _).findChildren(QWidget, options=direct),
#             )
#             self.roi_widget.setContentsMargins(0, 0, 0, 0)
#             # check if properties have setters and if not, disable widgets
#             for i, prop in enumerate(["width_px", "width_offset_px", "height_px", "height_offset_px"]):
#                 attr = getattr(type(camera), prop, False)
#                 if getattr(attr, "fset", None) is None:
#                     self.roi_widget.children()[i + 1].setEnabled(False)

#             central_widget = self.centralWidget()
#             central_widget.layout().setSpacing(0)  # remove space between central widget and newly formatted widgets
#             self.setCentralWidget(
#                 create_widget(
#                     "V",
#                     picture_buttons,
#                     pixel_widgets,
#                     timing_widgets,
#                     self.roi_widget,
#                     sensor_size_widget,
#                     central_widget,
#                 )
#             )
#         else:  # add snapshot button and liveview
#             central_widget = self.centralWidget()
#             central_widget.layout().setSpacing(0)  # remove space between central widget and newly formatted widgets
#             self.setCentralWidget(create_widget("H", self.live_button, self.snapshot_button))

#     def create_live_button(self) -> QPushButton:
#         """Add live button"""

#         button = QPushButton("Live")
#         icon = self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
#         button.setIcon(icon)

#         return button

#     def create_snapshot_button(self) -> QPushButton:
#         """Add snapshot button"""

#         button = QPushButton("Snapshot")
#         icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
#         button.setIcon(icon)
#         return button

#     def create_alignment_button(self) -> QPushButton:
#         """Add alignment button"""

#         button = QPushButton("Alignment")
#         icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ToolBarHorizontalExtensionButton)
#         button.setIcon(icon)
#         return button

#     def create_crosshairs_button(self) -> QPushButton:
#         """Add edges button"""

#         button = QPushButton("Crosshair")
#         icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DockWidgetCloseButton)
#         button.setIcon(icon)
#         return button
