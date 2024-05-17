import logging
import shutil
import datetime
import subprocess
import os
import sys
import inspect
import importlib
from pathlib import Path
from serial import Serial
from ruamel.yaml import YAML
from voxel.instruments.instrument import Instrument

class ExASPIM(Instrument):

    def __init__(self, config_filename: str):
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        # current working directory
        this_dir = Path(__file__).parent.resolve()
        self.config_path = this_dir / Path(config_filename)
        #yaml = YAML(typ='safe', pure=True)    # loads yaml in as dict. May want to use in future
        self.config = YAML(typ='safe', pure=True).load(self.config_path)

        # store a dict of {device name: device type} for convenience
        self.device_list = dict()
        # store a list of stage axes
        self.stage_axes = list()
        # store a dict of instrument channels
        self.channels = dict()
        # construct microscope
        self._construct()
        # verify constructed microscope
        self._verify_instrument()
        # verify master device for microscope
        self._verify_master_device()
        # verify channels for microscope
    #     self._verify_channels()
    #
    # def _verify_channels(self):
    #     setattr(self, 'channels', dict())
    #     for channel_name, channel in self.config['instrument']['channels'].items():
    #         self.channels[channel_name] = {
    #             'laser': channel['lasers'],
    #             'filter_wheel': channel['filter_wheel']
    #         }

    def _verify_master_device(self):
        """Define master_device dictionary if it is defined in yaml. master_device will be used later to calculate
        run time of acquisition"""

        if device_name := self.config['instrument'].get('master_device', False):
            self.master_device = {'name': device_name,
                                  'type': self.config['instrument']['devices'].get(device_name, None)['type']}
            if self.master_device['type'] == 'daq':
                master_task_dict = dict()
                for task_name, task in getattr(self, 'daqs')[device_name].tasks.items():
                    # the master device will not have triggering enabled
                    trigger_mode = task['timing']['trigger_mode']
                    if trigger_mode == 'off':
                        self.master_device['task'] = task_name
                        master_task_dict[task_name] = trigger_mode
                if len(master_task_dict.keys()) > 1:
                    raise ValueError(f'there can only be one master task. but {master_task_dict} are all master tasks.')

    def _verify_instrument(self):
        # assert that only one scanning stage is allowed
        self.log.info(f'verifying instrument configuration')
        num_scanning_stages = len(self.scanning_stages)
        if num_scanning_stages > 1:
            raise ValueError(f'only one scanning stage is allowed but {num_scanning_stages} detected')
        # assert that a NIDAQ must be present
        num_daqs = len(self.daqs)
        if num_daqs < 1:
            raise ValueError(f'at least one daq is required but {num_daqs} detected')
        # assert that a camera must be present
        num_cameras = len(self.cameras)
        if num_cameras < 1:
            raise ValueError(f'at least one camera is required but {num_cameras} detected')
        # assert that a laser must be present
        num_lasers = len(self.lasers)
        if num_lasers < 1:
            raise ValueError(f'at least one laser is required but {num_lasers} detected')