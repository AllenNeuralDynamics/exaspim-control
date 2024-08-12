from exaspim_control.exa_spim_view import ExASPIMInstrumentView, ExASPIMAcquisitionView
from exaspim_control.exa_spim_instrument import ExASPIM
from exaspim_control.exa_spim_acquisition import ExASPIMAcquisition
from datetime import datetime
from pathlib import Path
from aind_data_schema.core import acquisition
import numpy as np

class MetadataLaunch:
    """Launch script used to parse and save metadata according to aind-data-schema"""

    def __init__(self, instrument_config_filename: Path,
                 instrument_yaml_handler,
                 acquisition_config_filename: Path,
                 acquisition_yaml_handler,
                 gui_config_filename: Path,
                 log_level):

        """
        Create instrument, acquisition, and gui. Connect acquisitionEnded to parsing metadata method
        :param instrument_config_filename:
        :param instrument_yaml_handler:
        :param acquisition_config_filename:
        :param acquisition_yaml_handler:
        :param gui_config_filename:
        :param log_level:
        """

        # instrument
        self.instrument = ExASPIM(config_filename=instrument_config_filename,
                                  yaml_handler=instrument_yaml_handler,
                                  log_level=log_level)
        # acquisition
        self.acquisition = ExASPIMAcquisition(instrument=self.instrument,
                                              config_filename=acquisition_config_filename,
                                              yaml_handler=acquisition_yaml_handler,
                                              log_level=log_level)

        self.instrument_view = ExASPIMInstrumentView(self.instrument, gui_config_filename, log_level=log_level)
        self.acquisition_view = ExASPIMAcquisitionView(self.acquisition, self.instrument_view)

        self.acquisition_start_time = None  # variable will be filled when acquisitionStarted signal is emitted
        self.acquisition_view.acquisitionStarted.connect(lambda value: setattr(self, 'acquisition_start_time', value))
        self.acquisition_view.acquisitionEnded.connect(self.create_acquisition_json)

    def create_acquisition_json(self):
        """Method to create and save acquisition.json"""

        if getattr(self.acquisition, 'transfers', {}) != {}:  # save to external paths
            for device_name, transfer_dict in getattr(self.acquisition, 'transfers', {}).items():
                for transfer in transfer_dict.values():
                    save_to = str(Path(transfer.external_path, transfer.acquisition_name))
                    acquisition_model = self.parse_metadata(
                        external_drive=save_to,
                        local_drive=str(Path(transfer.local_path, transfer.acquisition_name)))
                    acquisition_model.write_standard_file(output_directory=save_to, prefix="exaspim")

        else:  # no transfers so save locally
            for device_name, writer_dict in self.writers.items():
                for writer in writer_dict.values():
                    save_to = str(Path(writer.local_path, writer.acquisition_name))
                    acquisition_model = self.parse_metadata(
                        external_drive=save_to,
                        local_drive=save_to)
                    acquisition_model.write_standard_file(output_directory=save_to, prefix="exaspim")

    def parse_metadata(self, external_drive:str, local_drive:str):
        """Method to parse through tiles to create an acquisition json
        :param external_drive: where data is transferred to
        :param local_drive: where data is written"""

        acq_dict = {'experimenter_full_name': getattr(self.acquisition.metadata, 'experimenter_full_name', []),
                    'specimen_id': str(getattr(self.acquisition.metadata, 'subject_id', '')),
                    'subject_id': str(getattr(self.acquisition.metadata, 'subject_id', '')),
                    'instrument_id': getattr(self.acquisition.metadata, 'instrument_id', ''),
                    'session_start_time': self.acquisition_start_time,
                    'session_end_time': datetime.now(),
                    'local_storage_directory': local_drive,
                    'external_storage_directory': external_drive,
                    'chamber_immersion': getattr(self.acquisition.metadata, 'chamber_immersion', None),
                    'axes': [
                        {
                            'name': 'X',
                            'dimension': 2,
                            'direction': getattr(self.acquisition.metadata, 'x_anatomical_direction', None)
                        },
                        {
                            'name': 'Y',
                            'dimension': 1,
                            'direction': getattr(self.acquisition.metadata, 'y_anatomical_direction', None)
                        },
                        {
                            'name': 'Z',
                            'dimension': 0,
                            'direction': getattr(self.acquisition.metadata, 'z_anatomical_direction', None)
                        }
                    ],
                    }
        tiles = []
        channels = self.instrument.config['instrument']['channels']
        for tile in self.acquisition.config['acquisition']['tiles']:
            tile_ch = tile['channel']
            laser = channels[tile_ch]['lasers'][0]  # FIXME: Is it okay to assume one laser for exaspim?
            excitation_wavelength = laser.split(' ')[0] # FIXME: Is it okay to assume this convention for all lasers? Or add to baseclass of lasers?
            tiles.append({
                'file_name': f"{tile['prefix']}_{tile['tile_number']:06}_ch_{tile_ch}_camera_"
                            f"{channels[tile_ch]['cameras'][0]}",  # FIXME: Is it okay to assume one camera for exaspim?
                'coordinate_transformations': [
                    {
                        "type": "scale",
                        "scale": [
                            "0.748",
                            "0.748",
                            "1"
                        ]
                    },
                    {
                        "type": "translation",
                        "translation": [
                            "0",
                            "0",
                            "0"
                        ]
                    }
                ],
                'channel': {
                    'channel_name': tile_ch,
                    "light_source_name": laser,  # FIXME: Is it okay to assume one laser for exaspim?
                    "filter_names": channels[tile_ch].get('filters', []),
                    "detector_name": channels[tile_ch]['cameras'][0],
                    "additional_device_names": np.array(
                        [x for x in channels[tile_ch] if x not in ['lasers', 'cameras']]).flatten(),
                    "excitation_wavelength": excitation_wavelength,
                    "excitation_power": tile[laser]['power_setpoint_mw'],  # FIXME: Is it okay to assume power setpoint always included?
                    "filter_wheel_index": 0
                }

            })
        acq_dict['tiles'] = tiles
        
        return acquisition.Acquisition(**acq_dict)
