import copy
import importlib
import inspect
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from threading import Lock, RLock
from typing import TYPE_CHECKING, Any

import inflection
from ruyaml import YAML
from serial import Serial
from voxel.descriptors.deliminated_property import _DeliminatedProperty
from voxel.devices.daq.base import VoxelDAQ

if TYPE_CHECKING:
    from voxel.devices.aotf.base import BaseAOTF
    from voxel.devices.base import VoxelDevice
    from voxel.devices.camera.base import BaseCamera
    from voxel.devices.filterwheel.base import BaseFilterWheel
    from voxel.devices.flip_mount.base import BaseFlipMount
    from voxel.devices.indicator_light.base import BaseIndicatorLight
    from voxel.devices.joystick.base import BaseJoystick
    from voxel.devices.laser.base import BaseLaser
    from voxel.devices.power_meter.base import BasePowerMeter
    from voxel.devices.rotation_mount.base import BaseRotationMount
    from voxel.devices.stage.asi.tiger import TigerStage
    from voxel.devices.temperature_sensor.base import BaseTemperatureSensor
    from voxel.devices.tunable_lens.base import BaseTunableLens


class Instrument(ABC):
    """Represents an instrument with various devices and configurations."""

    def __init__(self, config_path: str, yaml_handler: YAML | None = None, log_level: str = "INFO"):
        """
        Initialize the Instrument class.

        :param config_path: Path to the configuration file.
        :type config_path: str
        :param yaml_handler: YAML handler for loading and dumping config, defaults to None.
        :type yaml_handler: YAML, optional
        :param log_level: Logging level, defaults to "INFO".
        :type log_level: str, optional
        """
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.log.setLevel(log_level)

        # create yaml object to use when loading and dumping config
        self.yaml = yaml_handler if yaml_handler is not None else YAML(typ="safe")

        self.config_path = Path(config_path)
        self.config = self.yaml.load(self.config_path)

        # Initialize device dictionaries with proper types
        self.aotfs: dict[str, BaseAOTF] = {}
        self.camera: BaseCamera | None = None
        self.camera_name: str | None = None
        self.controllers: dict[str, VoxelDevice] = {}
        self.daq: VoxelDAQ | None = None
        self.daq_name: str | None = None
        self.filter_wheel: BaseFilterWheel | None = None
        self.filter_wheel_name: str | None = None
        self.flip_mounts: dict[str, BaseFlipMount] = {}
        self.focusing_stages: dict[str, TigerStage] = {}
        self.indicator_lights: dict[str, BaseIndicatorLight] = {}
        self.joysticks: dict[str, BaseJoystick] = {}
        self.lasers: dict[str, BaseLaser] = {}
        self.power_meters: dict[str, BasePowerMeter] = {}
        self.rotation_mounts: dict[str, BaseRotationMount] = {}
        self.scanning_stages: dict[str, TigerStage] = {}
        self.temperature_sensors: dict[str, BaseTemperatureSensor] = {}
        self.tiling_stages: dict[str, TigerStage] = {}
        self.tunable_lenses: dict[str, BaseTunableLens] = {}

        # store a dict of {device name: device type} for convenience
        self.channels: dict[str, Any] = {}
        self.stage_axes: list = []

        # construct microscope
        self._construct()

        errs = self._verify_instrument()
        if errs:
            msg = f"Instrument verification failed with errors: {errs}"
            raise ValueError(msg)

    @abstractmethod
    def _verify_instrument(self) -> list[str]: ...

    def _construct(self) -> None:
        """
        Construct the instrument from the configuration file.

        :raises ValueError: If the instrument ID or device configurations are invalid.
        """
        self.log.info(f"constructing instrument from {self.config_path}")
        # grab instrument id
        try:
            self.id = self.config["instrument"]["id"]
        except KeyError as e:
            raise ValueError("no instrument id defined. check yaml file.") from e
        # construct devices
        for device_name, device_specs in self.config["instrument"]["devices"].items():
            self._construct_device(device_name, device_specs)

        # TODO: need somecheck to make sure if multiple filters, they don't come from the same wheel
        # construct and verify channels
        for channel in self.config["instrument"]["channels"].values():
            for laser_name in channel.get("lasers", []):
                if laser_name not in self.lasers:
                    msg = f"laser {laser_name} not in {self.lasers.keys()}"
                    raise ValueError(msg)
            for filter in channel.get("filters", []):
                if filter not in self.filters:
                    msg = f"filter {filter} not in {self.filters.keys()}"
                    raise ValueError(msg)
                if self.filter_wheel is not None and filter not in self.filter_wheel.filters:
                    msg = f"filter {filter} not associated with filter wheel: {self.filter_wheel_name}"
                    raise ValueError(msg)
        self.channels = self.config["instrument"]["channels"]

    def _construct_device(
        self, device_name: str, device_specs: dict[str, Any], lock: "Lock | RLock | None" = None
    ) -> None:
        """
        Construct a device based on its specifications.

        :param device_name: Name of the device.
        :type device_name: str
        :param device_specs: Specifications of the device.
        :type device_specs: dict
        :param lock: Lock for thread safety, defaults to None.
        :type lock: Lock, optional
        :raises ValueError: If the device configuration is invalid.
        """
        self.log.info(f"constructing {device_name}")
        lock = RLock() if lock is None else lock
        device_type = inflection.pluralize(device_specs["type"])
        driver = device_specs["driver"]
        init = device_specs.get("init", {})
        device_object = self._load_device(driver, init, lock)
        properties = device_specs.get("properties", {})
        self._setup_device(device_object, properties)

        # Add device to the pre-initialized device dictionary or singular property
        if device_type == "cameras":
            self.camera = device_object
            self.camera_name = device_name
        elif device_type == "daqs":
            self.daq = device_object
            self.daq_name = device_name
        elif device_type == "filter_wheels":
            self.filter_wheel = device_object
            self.filter_wheel_name = device_name
        else:
            getattr(self, device_type)[device_name] = device_object

        # added logic for stages to store and check stage axes
        if device_type in {"tiling_stages", "scanning_stages"}:
            instrument_axis = device_specs["init"]["instrument_axis"]
            if instrument_axis in self.stage_axes:
                msg = f"{instrument_axis} is duplicated and already exists!"
                raise ValueError(msg)
            self.stage_axes.append(instrument_axis)

        # Add subdevices under device and fill in any needed keywords to init
        for subdevice_name, subdevice_specs in device_specs.get("subdevices", {}).items():
            # copy so config is not altered by adding in parent devices
            self._construct_subdevice(device_object, subdevice_name, copy.deepcopy(subdevice_specs), lock)

    def _construct_subdevice(
        self, device_object: Any, subdevice_name: str, subdevice_specs: dict[str, Any], lock: "Lock | RLock"
    ) -> None:
        """
        Construct a subdevice based on its specifications.

        :param device_object: Parent device object.
        :type device_object: object
        :param subdevice_name: Name of the subdevice.
        :type subdevice_name: str
        :param subdevice_specs: Specifications of the subdevice.
        :type subdevice_specs: dict
        :param lock: Lock for thread safety.
        :type lock: Lock
        """
        # Import subdevice class in order to access keyword argument required in the init of the device
        # Parse driver path: "module.path.ClassName" -> module_path, class_name
        driver_path = subdevice_specs["driver"]
        module_path, class_name = driver_path.rsplit(".", 1)
        subdevice_class = getattr(importlib.import_module(module_path), class_name)
        subdevice_needs = inspect.signature(subdevice_class.__init__).parameters
        for name, parameter in subdevice_needs.items():
            # If subdevice init needs a serial port, add device's serial port to init arguments
            if parameter.annotation == Serial and Serial in [type(v) for v in device_object.__dict__.values()]:
                # assuming only one relevant serial port in parent
                subdevice_specs["init"][name] = next(
                    v for v in device_object.__dict__.values() if isinstance(v, Serial)
                )
            # If subdevice init needs parent object type, add device object to init arguments
            elif parameter.annotation == type(device_object):
                subdevice_specs["init"][name] = device_object
        self._construct_device(subdevice_name, subdevice_specs, lock)

    def _load_device(self, driver: str, kwds: dict[str, Any], lock: "Lock | RLock") -> Any:
        """
        Load a device class and make it thread-safe.

        :param driver: Full driver path including class name (e.g., "voxel.devices.laser.cobolt.Cobolt0601Laser").
        :type driver: str
        :param kwds: Initialization keywords for the device.
        :type kwds: dict
        :param lock: Lock for thread safety.
        :type lock: Lock
        :return: Thread-safe device object.
        :rtype: object
        """
        # Parse driver path: "module.path.ClassName" -> module_path, class_name
        module_path, class_name = driver.rsplit(".", 1)
        self.log.info(f"loading {driver}")
        device_class = getattr(importlib.import_module(module_path), class_name)
        thread_safe_device_class = for_all_methods(lock, device_class)
        return thread_safe_device_class(**kwds)

    def _setup_device(self, device: Any, properties: dict[str, Any]) -> None:
        """
        Set up a device with its properties.

        :param device: Device object.
        :type device: object
        :param properties: Properties to set on the device.
        :type properties: dict
        """
        self.log.info(f"setting up {device}")
        # successively iterate through properties keys and if there is setter, set
        for key, value in properties.items():
            if hasattr(device, key):
                setattr(device, key, value)
            else:
                msg = f"{device} property {key} has no setter"
                raise ValueError(msg)

    def update_current_state_config(self) -> None:
        """
        Update the current state configuration of the instrument.
        """
        for device_name, device_specs in self.config["instrument"]["devices"].items():
            device = getattr(self, inflection.pluralize(device_specs["type"]))[device_name]
            properties = {}
            for attr_name in dir(device):
                attr = getattr(type(device), attr_name, None)
                if (
                    isinstance(attr, property) or isinstance(inspect.unwrap(attr), property)
                ) and attr_name != "latest_frame":
                    properties[attr_name] = getattr(device, attr_name)
            device_specs["properties"] = properties

    def save_config(self, path: Path, capture_current: bool = True) -> None:
        """
        Save the current configuration to a file.

        :param path: Path to save the configuration file.
        :type path: Path
        :param capture_current: Whether to update config with current device states before saving, defaults to True
        :type capture_current: bool, optional
        """
        if capture_current:
            self.update_current_state_config()
        with path.open("w") as f:
            self.yaml.dump(self.config, f)

    def close(self) -> None:
        """
        Close the instrument and release any resources.
        """
        self.log.warning("Instrument close not implemented")


def for_all_methods(lock: Lock, cls: type) -> type:
    """
    Apply a lock to all methods of a class to make them thread-safe.

    :param lock: Lock for thread safety.
    :type lock: Lock or RLock
    :param cls: Class to apply the lock to.
    :type cls: type
    :return: Class with thread-safe methods.
    :rtype: type
    """
    for attr_name in cls.__dict__:
        if attr_name == "__init__":
            continue
        attr = getattr(cls, attr_name)
        if isinstance(attr, _DeliminatedProperty):
            attr._fset = lock_methods(attr._fset, lock)
            attr._fget = lock_methods(attr._fget, lock)
        elif isinstance(attr, property):
            wrapped_getter = lock_methods(getattr(attr, "fget"), lock)
            # don't wrap setters if none
            wrapped_setter = lock_methods(getattr(attr, "fset"), lock) if getattr(attr, "fset") is not None else None
            setattr(cls, attr_name, property(wrapped_getter, wrapped_setter))
        elif callable(attr) and not isinstance(inspect.getattr_static(cls, attr_name), staticmethod):
            setattr(cls, attr_name, lock_methods(attr, lock))
    return cls


def lock_methods(fn: Callable, lock) -> Callable:
    """
    Apply a lock to a method to make it thread-safe.

    :param fn: Function to apply the lock to.
    :type fn: function
    :param lock: Lock for thread safety.
    :type lock: Lock or RLock
    :return: Thread-safe function.
    :rtype: function
    """

    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """
        Wrapper function to apply the lock.

        :return: Result of the original function.
        :rtype: Any
        """
        with lock:
            return fn(*args, **kwargs)

    return wrapper
