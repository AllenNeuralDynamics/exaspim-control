import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
from aind_data_schema.core import acquisition
from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_view import ExASPIMAcquisitionView, ExASPIMInstrumentView

X_ANATOMICAL_DIRECTIONS = {
    "Anterior_to_Posterior": "Anterior_to_posterior",
    "Posterior to Anterior": "Posterior_to_anterior",
}

Y_ANATOMICAL_DIRECTIONS = {
    "Inferior to Superior": "Inferior_to_superior",
    "Superior to Inferior": "Superior_to_inferior",
}

Z_ANATOMICAL_DIRECTIONS = {"Left to Right": "Left_to_right", "Right to Left": "Right_to_left"}


class MetadataLaunch:
    """Class for handling metadata launch for ExASPIM."""

    def __init__(
        self,
        instrument: ExASPIM,
        acquisition: ExASPIMAcquisition,
        instrument_view: ExASPIMInstrumentView,
        acquisition_view: ExASPIMAcquisitionView,
        log_filename: str = None,
    ):
        """
        Initialize the MetadataLaunch object.

        :param instrument: ExASPIM instrument object
        :type instrument: ExASPIM
        :param acquisition: ExASPIM acquisition object
        :type acquisition: ExASPIMAcquisition
        :param instrument_view: ExASPIM instrument view object
        :type instrument_view: ExASPIMInstrumentView
        :param acquisition_view: ExASPIM acquisition view object
        :type acquisition_view: ExASPIMAcquisitionView
        :param log_filename: Log filename, defaults to None
        :type log_filename: str, optional
        """
        # logger
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        # instrument
        self.instrument = instrument
        # acquisition
        self.acquisition = acquisition
        # guis
        self.instrument_view = instrument_view
        self.acquisition_view = acquisition_view
        # log filename
        self.log_filename = log_filename
        # start and finish the acquisition
        self.acquisition_start_time = None  # variable will be filled when acquisitionStarted signal is emitted
        self.acquisition_end_time = None  # variable will be filled when acquisitionStarted signal is emitted
        self.acquisition_view.acquisitionStarted.connect(lambda value: setattr(self, "acquisition_start_time", value))
        self.acquisition_view.acquisitionEnded.connect(lambda: setattr(self, "acquisition_end_time", datetime.now()))
        self.acquisition_view.acquisitionEnded.connect(self.finalize_acquisition)

    def finalize_acquisition(self) -> None:
        """
        Finalize the acquisition process.
        """
        self.log.info("Finalizing acquisition")
        # create and save acquisition.json
        if getattr(self.acquisition, "file_transfers", {}) != {}:  # save to external paths
            for device_name, transfer_dict in getattr(self.acquisition, "file_transfers", {}).items():
                for transfer in transfer_dict.values():
                    save_to = str(Path(transfer.external_path, transfer.acquisition_name))
                    acquisition_model = self.parse_metadata(
                        external_drive=save_to, local_drive=str(Path(transfer.local_path, transfer.acquisition_name))
                    )
                    acquisition_model.write_standard_file(output_directory=save_to, prefix="exaspim")
                    # move the log file
                    self.log.info(f"copying {self.log_filename} to {save_to}")
                    shutil.copy(
                        self.log_filename,
                        str(Path(save_to, self.log_filename)),
                    )
            # re-arrange external directory
            os.makedirs(Path(save_to, "exaSPIM"))
            os.makedirs(Path(save_to, "derivatives"))
            for file in os.listdir(save_to):
                if file.endswith(".ims"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "exaSPIM", file)))
                if file.endswith(".tiff"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "derivatives", file)))
            # delete local directory
            self.log.info(f"deleting {str(Path(transfer.local_path, transfer.acquisition_name))}")
            shutil.rmtree(str(Path(transfer.local_path, transfer.acquisition_name)))
        else:  # no transfers so save locally
            for device_name, writer_dict in self.acquisition.writers.items():
                for writer in writer_dict.values():
                    save_to = str(Path(writer.path, writer.acquisition_name))
                    acquisition_model = self.parse_metadata(external_drive=save_to, local_drive=save_to)
                    acquisition_model.write_standard_file(output_directory=save_to, prefix="exaspim")
                    # move the log file
                    self.log.info(f"copying {self.log_filename} to {save_to}")
                    shutil.copy(
                        self.log_filename,
                        str(Path(save_to, self.log_filename)),
                    )
            # re-arrange external directory
            os.makedirs(Path(save_to, "exaSPIM"))
            os.makedirs(Path(save_to, "derivatives"))
            for file in os.listdir(save_to):
                if file.endswith(".ims"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "exaSPIM", file)))
                if file.endswith(".tiff"):
                    os.rename(str(Path(save_to, file)), str(Path(save_to, "derivatives", file)))

    def parse_metadata(self, external_drive: str, local_drive: str) -> acquisition.Acquisition:
        """
        Parse metadata for the acquisition.

        :param external_drive: External storage directory
        :type external_drive: str
        :param local_drive: Local storage directory
        :type local_drive: str
        :return: Acquisition model
        :rtype: acquisition.Acquisition
        """
        acq_dict = {
            "experimenter_full_name": getattr(self.acquisition.metadata, "experimenter_full_name", []),
            "specimen_id": str(getattr(self.acquisition.metadata, "subject_id", "")),
            "subject_id": str(getattr(self.acquisition.metadata, "subject_id", "")),
            "instrument_id": getattr(self.acquisition.metadata, "instrument_id", ""),
            "session_start_time": self.acquisition_start_time,
            "session_end_time": self.acquisition_end_time,
            "local_storage_directory": local_drive,
            "external_storage_directory": external_drive,
            "chamber_immersion": getattr(self.acquisition.metadata, "chamber_immersion", None),
            "axes": [
                {
                    "name": "X",
                    "dimension": 2,
                    "direction": getattr(self.acquisition.metadata, "x_anatomical_direction", None),
                },
                {
                    "name": "Y",
                    "dimension": 1,
                    "direction": getattr(self.acquisition.metadata, "y_anatomical_direction", None),
                },
                {
                    "name": "Z",
                    "dimension": 0,
                    "direction": getattr(self.acquisition.metadata, "z_anatomical_direction", None),
                },
            ],
        }
        tiles = []
        channels = self.instrument.config["instrument"]["channels"]
        for tile in self.acquisition.config["acquisition"]["tiles"]:
            tile_ch = tile["channel"]
            laser = channels[tile_ch]["lasers"][0]
            excitation_wavelength = self.instrument.lasers[laser].wavelength
            tiles.append(
                {
                    "file_name": f"{tile['prefix']}_{tile['tile_number']:06}_ch_{tile_ch}_camera_"
                    f"{channels[tile_ch]['cameras'][0]}",
                    "coordinate_transformations": [
                        {"type": "scale", "scale": ["0.748", "0.748", "1"]},
                        {"type": "translation", "translation": ["0", "0", "0"]},
                    ],
                    "channel": {
                        "channel_name": tile_ch,
                        "light_source_name": laser,
                        "filter_names": channels[tile_ch].get("filters", []),
                        "detector_name": channels[tile_ch]["cameras"][0],
                        "additional_device_names": np.array(
                            [v for k, v in channels[tile_ch].items() if k not in ["lasers", "cameras"]]
                        ).flatten(),
                        "excitation_wavelength": excitation_wavelength,
                        "excitation_power": tile[laser]["power_setpoint_mw"],
                        "filter_wheel_index": 0,
                    },
                }
            )
        acq_dict["tiles"] = tiles

        return acquisition.Acquisition(**acq_dict)
