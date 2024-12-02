from view.widgets.base_device_widget import BaseDeviceWidget, create_widget, scan_for_properties
from qtpy.QtWidgets import QSizePolicy


class TunableLensWidget(BaseDeviceWidget):

    def __init__(self, tunable_lens):
        """
        Modify BaseDeviceWidget to be specifically for a tunable lens.
        :param tunable_lens: tunable lens object
        """

        self.tunable_lens_properties = scan_for_properties(tunable_lens)
        super().__init__(type(tunable_lens), self.tunable_lens_properties)

        modes = self.property_widgets["mode"].layout().itemAt(1).widget()
        modes.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        temperature = self.property_widgets["temperature_c"].layout().itemAt(1).widget()
        temperature.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)

        central_widget = self.centralWidget()
        central_widget.layout().setSpacing(0)  # remove space between central widget and newly formatted widgets
        self.setCentralWidget(create_widget("H", self.property_widgets["mode"], self.property_widgets["temperature_c"]))
