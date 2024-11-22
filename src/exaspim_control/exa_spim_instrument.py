import logging
from pathlib import Path
from ruamel.yaml import YAML
from voxel.instruments.instrument import Instrument

DIRECTORY = Path(__file__).parent.resolve()


class ExASPIM(Instrument):

    def __init__(self, config_filename: str, yaml_handler: YAML, log_level="INFO"):
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.log.setLevel(log_level)

        # current working directory
        super().__init__(DIRECTORY / Path(config_filename), yaml_handler, log_level)

        # verify constructed microscope
        self._verify_instrument()
        # verify master device for microscope
        self._verify_master_device()

    def _verify_master_device(self):
        """Define master_device dictionary if it is defined in yaml. master_device will be used later to calculate
        run time of acquisition"""

        if device_name := self.config["instrument"].get("master_device", False):
            self.master_device = {
                "name": device_name,
                "type": self.config["instrument"]["devices"].get(device_name, None)["type"],
            }
            if self.master_device["type"] == "daq":
                master_task_dict = dict()
                for task_name, task in getattr(self, "daqs")[device_name].tasks.items():
                    # the master device will not have triggering enabled
                    trigger_mode = task["timing"]["trigger_mode"]
                    if trigger_mode == "off":
                        self.master_device["task"] = task_name
                        master_task_dict[task_name] = trigger_mode
                if len(master_task_dict.keys()) > 1:
                    raise ValueError(f"there can only be one master task. but {master_task_dict} are all master tasks.")

    def _verify_instrument(self):
        # assert that only one scanning stage is allowed
        self.log.info(f"verifying instrument configuration")
        num_scanning_stages = len(self.scanning_stages)
        if num_scanning_stages > 1:
            raise ValueError(f"only one scanning stage is allowed but {num_scanning_stages} detected")
        # assert that a NIDAQ must be present
        num_daqs = len(self.daqs)
        if num_daqs < 1:
            raise ValueError(f"at least one daq is required but {num_daqs} detected")
        # assert that a camera must be present
        num_cameras = len(self.cameras)
        if num_cameras < 1:
            raise ValueError(f"at least one camera is required but {num_cameras} detected")
        # assert that a laser must be present
        num_lasers = len(self.lasers)
        if num_lasers < 1:
            raise ValueError(f"at least one laser is required but {num_lasers} detected")
