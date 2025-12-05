<h1>
    <div>
        <img src="voxel-logo.png" alt="Voxel Logo" width="50" height="50">
    </div>
    Voxel
</h1>

- [Overview](#overview)
  - [Devices](#device-list)
  - [Instrument](#instrument)
  - [Acquisition](#acquisition)
  - [Utilities](#utilities)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
  - [Documentation](#documentation)
  - [Usage](#usage)
- [Appendix](#appendix)
  - [Device List](#device-list)
  - [Writers](#writers)
  - [File Transfers](#file-transfers)
  - [Processes](#processes)
- [Support and Contribution](#support-and-contribution)
- [License](#license)

## Overview

Voxel is a Python package that provides core components and functionality for controlling Light Sheet Microscopy
systems. It is designed to simplify the process of developing software for novel microscope setups by focusing on
modular composable components. Voxel is built on the following principles:

1. **Modular**: Each component (device, writer, processor) implements a common interface and can be easily swapped out.
2. **Configurable**: Microscope setups are defined in a human readable YAML configuration file, allowing for easy setup and modification.
3. **Extensible**: New devices and components can be easily added by implementing the appropriate interface.
4. **Pythonic**: Written in Python and designed to be easily understood and modified.

### Devices

Voxel currently supports a number of different types of devices. Contributions for more devices is welcomed and only requires that new device drivers adhere to the corresponding device types base class. See the [full list of devices](#device-list).

> [!NOTE]
> Please see associated README files for cameras with additional [installation instructions](./src/voxel/devices/camera/README.md) for camera specific SDKs.

### Instrument

Voxel provides two key Classes: `Instrument` and `Acquisition`.

The `Instrument` class focuses on the composition and structure of the microscope setup. At its core, an instrument is a collection of devices that implement the `VoxelDevice` interface. An `instrument.yaml` file defines the devices and their respective settings. Devices are defined by providing their python package, module, and class name as well as any initialization arguments and settings.

Checkout an example [instrument configuration yaml](#2-instrument-yaml-configuration) and the [Devices](#device-list) section for a list of supported devices and their respective drivers.

### Acquisition

The `Acquisition` class focuses on the execution of an imaging experiment. It is responsible for coordinating the devices in the instrument to capture and process data. The `Acquisition` class is primarily set up as an abstract class that can be subclassed to implement specific acquisition protocols. It provides several methods that are useful in the implementation of an acquisition protocol. A run method is defined that should be overridden by the subclass in order to define a specific protocol for a given microscope design.
For an example of an acquisition protocol, check out the [ExA-SPIM Control](https://github.com/AllenNeuralDynamics/exaspim-control) repository.

### Utilities

Voxel also provides additional utilities useful for performing imaging experiments. This includes classes for writing data, performing online processing of imaging data, and concurrent transferring of data to external
storage.

Checkout the [Writers](#writers) and [File Transfers](#file-transfers) for a list of supported writers and file transfer methods and the [Processes](#processes) section for a list of supported processors.

## Getting Started

### Prerequisites

- **Python: >=3.10, <=3.11** (tested)
- We using a virtual environment:
  - [venv](https://docs.python.org/3.11/library/venv.html)
  - Conda: [Anaconda](https://www.anaconda.com/products/individual) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html))
- For control of some specific devices, you will need the appropriate SDK installed:
  - [Cameras](./src/voxel/devices/camera/README.md):
    - eGrabber (Windows and Linux)
    - DCAM (Windows only)
  - Lasers:
    - [Coherent HOPS](https://github.com/AllenNeuralDynamics/coherent_lasers) (Windows only)
  - [Tunable Lenses](./src/voxel//devices//tunable_lens/README.md):
    - [optoICC](https://www.optotune.com/software-center)
    - [optooptoKummenberg](https://www.optotune.com/software-center)

### Installation

1. Create a virtual environment and activate it:
    On Windows:

    ```bash
    conda create -n voxel
    conda activate voxel
    ```

    or

    ```bash
    python -m venv voxel
    .\voxel\Scripts\activate
    ```

2. Clone the repository:

    ```bash
    git clone https://github.com/AllenNeuralDynamics/voxel.git && cd voxel
    ```

3. To use the software, in the root directory, run:

    ```bash
    pip install -e .
    ```

4. To develop the code, run:

    ```bash
    pip install -e .[dev]
    ```

5. To install all dependencies including all optional device drivers, run:

    ```bash
    pip install -e .[all]
    ```

6. To install specific device drivers that have SDK requirements, run:

    ```bash
    pip install -e .[imaris tiff]
    ```

Check out the [list of supported devices](#device-list) for more information on device drivers.

### Documentation

- _(coming soon)_

### Usage

#### 1. Single device

Individual device can be instantiated by importing the appropriate driver
class with the expected arguments. For example a camera object for a Vieworks
VP-151MX can be invoked as:

```python
from voxel.devices.camera.vieworks_egrabber import VieworksCamera

camera = VieworksCamera(id='123456')
```

Camera properties can then be queried and set by accessing attributes of the
camera object:

```python
camera.exposure_time ms = 10.0
camera.pixel_type = 'mono16'
camera.bit_packing_mode = 'lsb'
camera.binning = 1
camera.width_px = 14192
camera.height_px = 10640
camera.trigger = {'mode': 'on', 'source': 'line0', 'polarity': 'risingedge'}
```

The camera can then be operated with:

```python
camera.prepare() # this function arms and creates the camera buffer
camera.start()
image = camera.grab_frame()
camera.stop()
camera.close()
```

#### 2. Instrument YAML configuration

```yaml
instrument:
    devices:
        vp-151mx camera:
            type: camera
            driver: voxel.devices.camera.simulated
            module: SimulatedCamera
            init:
                id: 123456
            properties:
                exposure_time_ms: 10.0
                pixel_type: mono16
                height_offest_px: 0
                height_px: 2048
                width_offset_px: 0
                width_px: 2048
                trigger:
                    mode: off
                    polarity: rising
                    source: external
        488 nm laser:
            type: laser
            driver: voxel.devices.laser.simulated
            module: SimulatedLaser
            init:
                id: COM1
                wavelength_nm: 488
        x axis stage:
            type: scanning_stage
            driver: voxel.devices.stage.simulated
            module: SimulatedStage
            init:
                hardware_axis: x
                instrument_axis: z
            properties:
                speed_mm_s: 1.0
```

An instrument can be invoked by loading the YAML file with and the loaded devices
can be accessed with. The above example uses all simulated device classes.

```python
from voxel.instruments.instrument import Instrument

instrument = Instrument(config_path='example.yaml')
instrument.cameras['vp-151mx camera']
instrument.lasers['488 nm laser']
instrument.scanning_stages['x axis stage']
```

#### 3. Experimental workflows may then be scripted by using the full instrument object and the contained device objects as needed

- _(example coming soon)_

## Appendix

### Device List

Currently supported device types and models are listed below.

#### DAQ

| Manufacturer         | Model     | Class        | Module                        | Tested |
| -------------------- | --------- | ------------ | ----------------------------- | ------ |
| Simulated            | Mock   | SimulatedDAQ | `voxel.devices.daq.simulated` | ✅      |
| National Instruments | PCIe-6738 | NIDAQ        | `voxel.devices.daq.ni`        | ✅      |

#### Cameras

| Manufacturer | Model            | Class           | Module                           | Tested |
| ------------ | ---------------- | --------------- | -------------------------------- | ------ |
| Simulated    | Mock       | SimulatedCamera | `voxel.devices.camera.simulated` | ✅      |
| Vieworks     | VP-151MX         | VieworksCamera  | `voxel.devices.camera.vieworks.egrabber`  | ✅      |
| Vieworks     | VNP-604MX        | VieworksCamera  | `voxel.devices.camera.vieworks.egrabber`  | ✅      |
| Ximea     | MX2457MR-SY-X4G3-FF | XIAPICamera  | `voxel.devices.camera.ximea.xiapi`  | ✅      |
| Hamamatsu    | ORCA-Flash4.0 V3 | DCAMCamera | `voxel.devices.camera.hamamatsu.dcam` | ✅      |
| Hamamatsu    | ORCA-Fusion BT   | DCAMCamera | `voxel.devices.camera.hamamatsu.dcam` | ✅      |
| PCO          | ----             | PCOCamera       | `voxel.devices.camera.pco.pco`       | ❌      |

#### Lasers

| Manufacturer | Model     | Class          | Module                                     | Tested |
| ------------ | --------- | -------------- | ------------------------------------------ | ------ |
| Simulated    | Mock | SimulatedLaser | `voxel.devices.laser.simulated`            | ✅      |
| Coherent     | OBISLX    | ObixLXLaser    | `voxel.devices.laser.coherent.obis_lx`             | ✅      |
| Coherent     | OBISLS    | ObixLSLaser    | `voxel.devices.laser.coherent.obis_ls`             | ✅      |
| Coherent     | GenesisMX | GenesisMXVoxel | `voxel.devices.laser.coherent.genesis_mx` | ✅      |
| Vortran      | Stradus   | StradusLaser   | `voxel.devices.laser.vortran.stradus`              | ❌      |
| Oxxius       | LBX       | OxxiusLBXLaser | `voxel.devices.laser.oxxius.lbx`               | ❌      |
| Oxxius       | LCX       | OxxiusLCXLaser | `voxel.devices.laser.oxxius.lcx`               | ❌      |
| Cobolt       | Skyra     | CoboltLaser    | `voxel.devices.laser.cobolt.skyra`               | ❌      |

#### Stages

| Manufacturer | Model     | Class          | Module                          | Tested |
| ------------ | --------- | -------------- | ------------------------------- | ------ |
| Simulated    | Mock | SimulatedStage | `voxel.devices.stage.simulated` | ✅      |
| ASI          | Tiger     | TigerStage       | `voxel.devices.stage.asi.tiger`       | ✅      |

#### Rotation mounts

| Manufacturer | Model  | Class       | Module                                   | Tested |
| ------------ | ------ | ----------- | ---------------------------------------- | ------ |
| Simulated    | Mock | SimulatedRotationMount | `voxel.devices.rotation_mount.simulated` | ✅      |
| Thorlabs     | K10CR1 | K10CR1Mount  | `voxel.devices.rotation_mount.thorlabs.k10cr1`  | ✅      |

#### AOTF

| Manufacturer | Model    | Class         | Module                         | Tested |
| ------------ | -------- | ------------- | ------------------------------ | ------ |
| Simulated    | Mock | SimulatedAOTF | `voxel.devices.aotf.simulated` | ✅      |
| AAOpto       | MPDSxx   | AAOptoAOTF    | `voxel.devices.aotf.aaopto.aotfnc`    | ❌      |

#### Filterwheel

| Manufacturer | Model   | Class          | Module                                | Tested |
| ------------ | ------- | -------------- | ------------------------------------- | ------ |
| Simulated    | Mock  | SimulatedFilteWheel    | `voxel.devices.filterwheel.simulated` | ✅      |
| ASI          | FW-1000 | FW1000FilterWheel | `voxel.devices.filterwheel.asi.fw1000`       | ✅      |

#### Flip mount

| Manufacturer | Model  | Class       | Module                               | Tested |
| ------------ | ------ | ----------- | ------------------------------------ | ------ |
| Simulated    | Mock | SimulatedFlipMount | `voxel.devices.flip_mount.simulated` | ✅      |
| Thorlabs     | MFF101 | MFF101FlipMount  | `voxel.devices.flip_mount.thorlabs.mff101`  | ✅      |

#### Power meter

| Manufacturer | Model  | Class       | Module                                | Tested |
| ------------ | ------ | ----------- | ------------------------------------- | ------ |
| Simulated    | Mock | SimulatedPowerMeter | `voxel.devices.power_meter.simulated` | ✅      |
| Thorlabs     | PM100D | PM100PowerMeter  | `voxel.devices.power_meter.thorlabs.pm100`  | ✅      |

#### Tunable lens

| Manufacturer | Model        | Class          | Module                                 | Tested |
| ------------ | ------------ | -------------- | -------------------------------------- | ------ |
| Simulated    | Mock       | SimulatedTunableLens    | `voxel.devices.tunable_lens.simulated` | ✅      |
| ASI          | TGTLC        | TGTLCTunableLens | `voxel.devices.tunable_lens.asi.tgtlc`       | ✅      |
| Optotune     | ELE4i | ELE4ITunableLens     | `voxel.devices.tunable_lens.optotune.ele4i`  | ✅  |
| Optotune     | ICC4C | ICC4CTunableLens     | `voxel.devices.tunable_lens.optotune.icc4c`  | ✅  |

#### Temperature / humidity sensor

| Manufacturer | Model        | Class          | Module                                 | Tested |
| ------------ | ------------ | -------------- | -------------------------------------- | ------ |
| Simulated    | Mock      | SimulatedTemperatureSensor    | `voxel.devices.temperature_sensor.tsp0b1` | ✅ |
| Thorlabs    | TSP0B1       | TSP0B1TemperatureSensor    | `voxel.devices.temperature_sensor.tsp0b1` | ✅ |

### Writers

| Writer  | File Format   | Class         | Module                  | Tested |
| ------- | ------------- | ------------- | ------------------------| ------ |
| Imaris  | `.ims`        | ImarisWriter  | `voxel.writers.imaris`  | ✅      |
| TIFF    | `.tiff`       | TIFFWriter    | `voxel.writers.tiff`    | ✅      |
| BDV     | `.h5/.xml`    | BDVWriter     | `voxel.writers.bdv`     | ✅      |
| [ACQUIRE](https://pypi.org/project/acquire-zarr/) | `.zarr V2/V3` | ZarrWriter    | `voxel.writers.zarr`    | ✅      |

> [!WARNING]
> [Acquire-Zarr](https://pypi.org/project/acquire-zarr/) is a Python API into a video streaming Zarr V2/V3 writer from the [Acquire Project](https://github.com/acquire-project). It is still actively being developed. This writer class is in developement. Although this beta version works, it still needs more thorough testing.

### File Transfers

| Transfer Method | Class    | Module                         | Tested |
| --------------- | -------- | ------------------------------ | ------ |
| Robocopy        | RobocopyFileTransfer | `voxel.file_transfer.robocopy` | ✅      |
| Rsync           | RsyncFileTransfer    | `voxel.file_transfer.rsync`    | ✅      |

> [!NOTE]
> On Windows, we suggest using Robocopy for transferring files. On Unix, we suggest using Rsync. Rsync is availble on windows and can be installed from a number of sources. For example [cwRsync](https://itefix.net/cwrsync).

### Processes

```yaml
CPU processes:
    - Downsample 2D
    - Downsample 3D
    - Maximum projections (xy, xz, yz)
GPU processes:
    - Downsample 2D
    - Downsample 3D
    - Rank-ordered downsample 3D
```

## Support and Contribution

If you encounter any problems or would like to contribute to the project,
please submit an [Issue](https://github.com/AllenNeuralDynamics/voxel/issues)
on GitHub.

## License

Voxel is licensed under the MIT License. For more details, see
the [LICENSE](LICENSE) file.
