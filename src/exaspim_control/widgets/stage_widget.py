from view.widgets.base_device_widget import BaseDeviceWidget, scan_for_properties
from qtpy.QtWidgets import QLabel
from qtpy.QtGui import QDoubleValidator, QIntValidator
from view.widgets.miscellaneous_widgets.q_scrollable_line_edit import QScrollableLineEdit
import importlib


class StageWidget(BaseDeviceWidget):

    def __init__(self, stage, advanced_user: bool = True):
        """
        Modify BaseDeviceWidget to be specifically for Stage. Main need is advanced user.
        :param stage: stage object
        :param advanced_user: boolean specifying complexity of widget. If False, only position is shown
        """

        self.stage_properties = scan_for_properties(stage) if advanced_user else {"position_mm": stage.position_mm}

        self.stage_module = importlib.import_module(stage.__module__)
        super().__init__(type(stage), self.stage_properties)

        # alter position_mm widget to use instrument_axis as label
        self.property_widgets["position_mm"].setEnabled(False)
        position_label = self.property_widgets["position_mm"].findChild(QLabel)
        # TODO: Change when deliminated property is updated
        unit = getattr(type(stage).position_mm, "unit", "mm")
        # TODO: Change and add rotation stage to voxel devices
        if stage.instrument_axis in ["t", "r"]:  # rotation stages
            unit = "°"
        position_label.setText(f"{stage.instrument_axis} [{unit}]")

        # update property_widgets['position_mm'] text to be white
        style = """
        QScrollableLineEdit {
            color: white;
        }

        QLabel {
            color : white;
        }
        """
        self.property_widgets["position_mm"].setStyleSheet(style)

    def create_text_box(self, name, value):
        """Convenience function to build editable text boxes and add initial value and validator
        :param name: name to emit when text is edited is changed
        :param value: initial value to add to box"""

        value_type = type(value)
        textbox = QScrollableLineEdit(str(value))
        textbox.editingFinished.connect(lambda: self.textbox_edited(name))
        if float in value_type.__mro__:
            validator = QDoubleValidator()
            validator.setNotation(QDoubleValidator.StandardNotation)
            validator.setDecimals(3)
            textbox.setValidator(validator)
            textbox.setValue(round(value, 3))
        elif int in value_type.__mro__:
            validator = QIntValidator()
            textbox.setValidator(validator)
        return textbox
