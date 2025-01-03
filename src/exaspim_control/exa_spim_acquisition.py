import os
import platform
import shutil
import subprocess
import threading
import time
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from threading import Event, Lock

import inflection
import numpy
from gputools import get_device
from psutil import virtual_memory
from ruamel.yaml import YAML

from voxel.acquisition.acquisition import Acquisition
from voxel.instruments.instrument import Instrument
from voxel.writers.data_structures.shared_double_buffer import SharedDoubleBuffer

DIRECTORY = Path(__file__).parent.resolve()


class ExASPIMAcquisition(Acquisition):
    """Class for handling ExASPIM acquisition."""

    def __init__(self, instrument: Instrument, config_filename: str, yaml_handler: YAML, log_level="INFO"):
        """
        Initialize the ExASPIMAcquisition object.

        :param instrument: Instrument object
        :type instrument: Instrument
        :param config_filename: Configuration filename
        :type config_filename: str
        :param yaml_handler: YAML handler
        :type yaml_handler: YAML
        :param log_level: Logging level, defaults to "INFO"
        :type log_level: str, optional
        """
        self.metadata = None  # initialize as none since setting up metadata class with call setup_class
        super().__init__(instrument, DIRECTORY / Path(config_filename), yaml_handler, log_level)

        # store acquisition name
        self.acquisition_name = self.metadata.acquisition_name

        # verify acquisition
        self._verify_acquisition()

        # initialize stop engine event
        self.stop_engine = Event()

    def _setup_class(self, device: object, settings: dict) -> None:
        """
        Overwrite to allow metadata class to pass in acquisition_name to devices that require it.

        :param device: Device object
        :type device: object
        :param settings: Settings dictionary
        :type settings: dict
        """
        super()._setup_class(device, settings)

        # set acquisition_name attribute if it exists for object
        if hasattr(device, "acquisition_name") and self.metadata is not None:
            setattr(device, "acquisition_name", self.metadata.acquisition_name)

    def run(self) -> None:
        """
        Run the acquisition process.

        :raises ValueError: If tile frame count is less than chunk size
        :raises ValueError: If there is not enough local disk space
        """

        # verify acquisition
        self._verify_acquisition()

        # set acquisition name
        self._set_acquisition_name()

        # create directories
        self._create_directories()

        # initialize threads and buffers
        file_transfer_threads = dict()

        # store devices and routines
        camera, camera_name = self._grab_first(self.instrument.cameras)  # only 1 camera for exaspim
        scanning_stage, _ = self._grab_first(self.instrument.scanning_stages)  # only 1 scanning stage for exaspim
        daq, _ = self._grab_first(self.instrument.daqs)  # only 1 daq for exaspim
        writer, _ = self._grab_first(self.writers[camera_name])  # only 1 writer for exaspim
        if self.file_transfers:
            file_transfer, _ = self._grab_first(self.file_transfers[camera_name])  # only 1 file transfer for exaspim
        else:
            file_transfer = dict()
        processes = self.processes[camera_name]  # processes could be > so leave as a dictionary

        for tile in self.config["acquisition"]["tiles"]:

            tile_num = tile["tile_number"]
            tile_channel = tile["channel"]
            tile_prefix = tile["prefix"]
            base_filename = f"{tile_prefix}_{tile_num:06}_ch_{tile_channel}"

            # check length of scan
            chunk_count_px = writer.chunk_count_px
            tile_count_px = tile["steps"]
            if tile_count_px < chunk_count_px:
                raise ValueError(
                    f"tile frame count {tile_count_px} \
                    is less than chunk size = {chunk_count_px} px"
                )

            # move all tiling stages to correct positions
            for tiling_stage_id, tiling_stage in self.instrument.tiling_stages.items():
                # grab stage axis letter
                instrument_axis = tiling_stage.instrument_axis
                tile_position = tile["position_mm"][instrument_axis]
                self.log.info(f"moving stage {tiling_stage_id} to {instrument_axis} = {tile_position} mm")
                tiling_stage.move_absolute_mm(tile_position, wait=False)
                # wait on tiling stage
                while tiling_stage.is_axis_moving():
                    self.log.info(
                        f"waiting for stage {tiling_stage_id}: {instrument_axis} ="
                        f"{tiling_stage.position_mm} -> {tile_position} mm"
                    )
                    time.sleep(1.0)

            # prepare the scanning stage for step and shoot behavior
            self.log.info("setting up scanning stage")
            instrument_axis = scanning_stage.instrument_axis
            tile_position = tile["position_mm"][instrument_axis]
            backlash_removal_position = tile_position - 0.01
            self.log.info(f"moving scanning stage to {instrument_axis} = {backlash_removal_position} mm")
            scanning_stage.move_absolute_mm(tile_position - 0.01, wait=False)
            self.log.info(f"moving stage to {instrument_axis} = {tile_position} mm")
            scanning_stage.move_absolute_mm(tile_position, wait=False)
            self.log.info("backlash on scanning stage removed")
            step_size_um = tile["step_size"]
            self.log.info(f"setting step shoot scan step size to {step_size_um} um")
            scanning_stage.setup_step_shoot_scan(step_size_um)
            # wait on scanning stage
            while scanning_stage.is_axis_moving():
                self.log.info(
                    f"waiting for scanning stage: {instrument_axis} = "
                    f"{scanning_stage.position_mm} -> {tile_position} mm"
                )

            # setup channel i.e. laser and filter wheels
            self.log.info(f"setting up channel: {tile_channel}")
            channel = self.instrument.channels[tile_channel]
            for device_type, devices in channel.items():
                for device_name in devices:
                    device = getattr(self.instrument, device_type)[device_name]
                    if device_type in ["lasers", "filters"]:
                        device.enable()
                    for setting, value in tile.get(device_name, {}).items():
                        setattr(device, setting, value)
                        self.log.info(f"setting {setting} for {device_type} {device_name} to {value}")

            # setup daq
            if daq.tasks.get("ao_task", None) is not None:
                daq.add_task("ao")
                daq.generate_waveforms("ao", tile_channel)
                daq.write_ao_waveforms()
            if daq.tasks.get("do_task", None) is not None:
                daq.add_task("do")
                daq.generate_waveforms("do", tile_channel)
                daq.write_do_waveforms()
            if daq.tasks.get("co_task", None) is not None:
                pulse_count = writer.chunk_count_px  # number of pulses matched to number of frames in one chunk
                daq.add_task("co", pulse_count)

            # log daq values
            for name, port_values in daq.tasks["ao_task"]["ports"].items():
                parameters = port_values["parameters"]
                port = port_values["port"]
                for parameter, channel_values in parameters.items():
                    daq_value = channel_values["channels"][tile_channel]
                    self.log.info(f"{name} on {port}: {parameter} = {daq_value}")

            # run any pre-routines for all devices
            for device_name, routine_dictionary in getattr(self, "routines", {}).items():
                device_type = self.instrument.config["instrument"]["devices"][device_name]["type"]
                self.log.info(f"running routines for {device_type} {device_name}")
                for routine_name, routine in routine_dictionary.items():
                    device_object = getattr(self.instrument, inflection.pluralize(device_type))[device_name]
                    routine.filename = base_filename + "_" + routine_name
                    routine.start(device=device_object)

            # setup camera, data writing engines, and processes
            self.log.info("arming camera and writer")
            self.engine(tile, base_filename, camera, daq, writer, processes)

            # stop the daq
            self.log.info("stopping daq")
            daq.stop()

            # disable scanning stage stepping
            scanning_stage.mode = "off"  # turn off step and shoot mode

            # create and start transfer threads from previous tile
            if tile_num not in file_transfer_threads:
                file_transfer_threads[tile_num] = dict()
            file_transfer_threads[tile_num][tile_channel] = file_transfer
            file_transfer_threads[tile_num][tile_channel].filename = base_filename
            self.log.info(f"starting file transfer for {base_filename}")
            file_transfer_threads[tile_num][tile_channel].start()

        # wait for last tiles file transfer
        for tile_num, threads_dict in file_transfer_threads.items():
            for tile_channel, thread in threads_dict.items():
                if thread.is_alive():
                    thread.wait_until_finished()

        if getattr(self, "file_transfers", {}) != {}:  # save to external paths
            # save acquisition config
            for device_name, transfer_dict in getattr(self, "file_transfers", {}).items():
                for transfer in transfer_dict.values():
                    self.update_current_state_config()
                    self.save_config(
                        Path(transfer.external_path, transfer.acquisition_name) / "acquisition_config.yaml"
                    )

            # save instrument config
            for device_name, transfer_dict in getattr(self, "file_transfers", {}).items():
                for transfer in transfer_dict.values():
                    self.instrument.update_current_state_config()
                    self.instrument.save_config(
                        Path(transfer.external_path, transfer.acquisition_name) / "instrument_config.yaml"
                    )

        else:  # no transfers so save locally
            # save acquisition config
            for device_name, writer_dict in self.writers.items():
                for writer in writer_dict.values():
                    self.update_current_state_config()
                    self.save_config(Path(writer.path, writer.acquisition_name) / "acquisition_config.yaml")

            # save instrument config
            for device_name, writer_dict in self.writers.items():
                for writer in writer_dict.values():
                    self.instrument.update_current_state_config()
                    self.instrument.save_config(Path(writer.path, writer.acquisition_name) / "instrument_config.yaml")

    def engine(
        self, tile: dict, base_filename: str, camera: object, daq: object, writer: object, processes: dict
    ) -> None:
        """
        Setup and run the acquisition engine.

        :param tile: Tile configuration
        :type tile: dict
        :param base_filename: Base filename for the acquisition
        :type base_filename: str
        :param camera: Camera object
        :type camera: object
        :param writer: Writer object
        :type writer: object
        :param processes: Processes dictionary
        :type processes: dict
        :raises ValueError: If there is not enough local disk space
        """

        # initatlized shared double buffer and processes
        process_buffers = dict()
        chunk_lock = Lock()
        img_buffer = SharedDoubleBuffer(
            (writer.chunk_count_px, camera.image_height_px, camera.image_width_px),
            dtype=writer.data_type,
        )

        # setup writers
        writer.row_count_px = camera.image_height_px
        writer.column_count_px = camera.image_width_px
        writer.frame_count_px = tile["steps"]
        writer.x_position_mm = tile["position_mm"]["x"]
        writer.y_position_mm = tile["position_mm"]["y"]
        writer.z_position_mm = tile["position_mm"]["z"]
        writer.x_voxel_size_um = camera.sampling_um_px
        writer.y_voxel_size_um = camera.sampling_um_px
        writer.z_voxel_size_um = tile["step_size"]
        writer.filename = base_filename
        writer.channel = tile["channel"]

        # setup processes
        for process_name, process in processes.items():
            process.row_count_px = camera.image_height_px
            process.column_count_px = camera.image_width_px
            process.binning = camera.binning
            process.frame_count_px = tile["steps"]
            process.filename = base_filename
            img_bytes = (
                numpy.prod(camera.image_height_px * camera.image_width_px) * numpy.dtype(process.data_type).itemsize
            )
            buffer = SharedMemory(create=True, size=int(img_bytes))
            process_buffers[process_name] = buffer
            process.buffer_image = numpy.ndarray(
                (camera.image_height_px, camera.image_width_px),
                dtype=process.data_type,
                buffer=buffer.buf,
            )
            process.prepare(buffer.name)

        # check local disk space and run if enough disk space
        if self.check_local_tile_disk_space(tile):

            # set up writer and camera
            camera.prepare()
            writer.prepare()
            writer.start()
            time.sleep(1)

            # start camera
            camera.start()

            # start processes
            for process in processes.values():
                process.start()

            frame_index = 0
            last_frame_index = tile["steps"] - 1

            # Images arrive serialized in repeating channel order.
            for stack_index in range(tile["steps"]):
                if self.stop_engine.is_set():
                    break
                chunk_index = stack_index % writer.chunk_count_px
                # Start a batch of pulses to generate more frames and movements.
                if chunk_index == 0:
                    self.log.info("starting daq")
                    for task in [daq.ao_task, daq.do_task, daq.co_task]:
                        if task is not None:
                            task.start()

                # Grab camera frame and add to shared double buffer.
                current_frame = camera.grab_frame()
                img_buffer.add_image(current_frame)

                # Log the current state of the camera.
                camera.signal_acquisition_state()

                # Log the current state of the writer.
                while not writer._log_queue.empty():
                    self.log.info(f"writer: {writer._log_queue.get_nowait()}")

                # Dispatch either a full chunk of frames or the last chunk,
                # which may not be a multiple of the chunk size.
                if chunk_index + 1 == writer.chunk_count_px or stack_index == last_frame_index:
                    daq.stop()
                    # Toggle double buffer to continue writing images.
                    while not writer.done_reading.is_set() and not self.stop_engine.is_set():
                        time.sleep(0.001)
                    with chunk_lock:
                        img_buffer.toggle_buffers()
                        writer.shm_name = img_buffer.read_buf_mem_name
                        writer.done_reading.clear()

                # check on processes
                for process in processes.values():
                    while process.new_image.is_set():
                        time.sleep(0.1)
                    process.buffer_image[:, :] = current_frame
                    process.new_image.set()

                frame_index += 1

            # stop the camera
            camera.stop()

            # wait for the writer to finish
            writer.wait_to_finish()

            # log any statements in the writer log queue
            while not writer._log_queue.empty():
                self.log.info(writer._log_queue.get_nowait())

            # wait for the processes to finish
            for process in processes.values():
                process.wait_to_finish()

            # clean up the image buffer
            self.log.info("deallocating shared double buffer.")
            img_buffer.close_and_unlink()
            del img_buffer
            for buffer in process_buffers.values():
                buffer.close()
                buffer.unlink()
                del buffer

        # if not enough local disk space, but file transfers are running
        # wait for them to finish, because this will free up disk space
        elif len(self.file_transfer_threads) != 0:
            # check if any transfer threads are still running, if so wait on them
            for tile_num, threads_dict in self.file_transfer_threads.items():
                for tile_channel, transfer_thread in threads_dict.items():
                    if transfer_thread.is_alive():
                        transfer_thread.wait_until_finished()

        # otherwise this is the first tile and there is simply not enough disk space
        # for the first tile
        else:
            raise ValueError("not enough local disk space")

    def stop_acquisition(self) -> None:
        """
        Overwrite to better stop acquisition.
        """
        self.stop_engine.set()
        raise RuntimeError

    @property
    def acquisition_rate_hz(self, daq: object) -> float:
        """
        Get the acquisition rate in Hz.

        :param daq: DAQ object
        :type daq: object
        :return: Acquisition rate in Hz
        :rtype: float
        """
        acquisition_rate_hz = 1.0 / daq.co_task.timing.task_time_s
        return acquisition_rate_hz

    def _grab_first(self, object_dict: dict) -> object:
        """
        Grab the first object from a dictionary.

        :param object_dict: Dictionary containing devices
        :type object_dict: dict
        :return: The first device in the dictionary
        :rtype: object
        """
        object_name = list(object_dict.keys())[0]
        return object_dict[object_name], object_name

    def _set_acquisition_name(self) -> None:
        """
        Sets the acquisition name for all operations.
        """
        for device_name, operation_dict in self.config["acquisition"]["operations"].items():
            for op_name, op_specs in operation_dict.items():
                op_type = inflection.pluralize(op_specs["type"])
                operation = getattr(self, op_type)[device_name][op_name]
                if hasattr(operation, "acquisition_name"):
                    setattr(operation, "acquisition_name", self.acquisition_name)

    def _create_directories(self) -> None:
        """
        Creates necessary directories for acquisition.
        """
        self.log.info("creating local and external directories")

        # check if local directories exist and create if not
        for writer_dictionary in self.writers.values():
            for writer in writer_dictionary.values():
                local_path = Path(writer.path, self.acquisition_name)
                if not os.path.isdir(local_path):
                    os.makedirs(local_path)
        # check if external directories exist and create if not
        if hasattr(self, "transfers"):
            for transfer_dictionary in self.transfers.values():
                for transfer in transfer_dictionary.values():
                    external_path = Path(transfer.external_path, self.acquisition_name)
                    if not os.path.isdir(external_path):
                        os.makedirs(external_path)

    def _verify_acquisition(self) -> None:
        """
        Verifies the acquisition configuration.

        :raises ValueError: If any configuration issues are found.
        """
        self.log.info("verifying acquisition configuration")

        # check that there is an associated writer for each camera
        for camera_id, camera in self.instrument.cameras.items():
            if camera_id not in self.writers.keys():
                raise ValueError(f"no writer found for camera {camera_id}. check yaml files.")

        # check that files won't be overwritten if multiple writers/transfers per device
        for device_name, writers in self.writers.items():
            paths = [write.path for write in writers.values()]
            if len(paths) != len(set(paths)):
                raise ValueError(
                    f"More than one operation for device {device_name} is writing to the same folder. "
                    f"This will cause data to be overwritten."
                )
        # check that files won't be overwritten if multiple writers/transfers per device
        for device_name, transfers in getattr(self, "transfers", {}).items():
            external_directories = [transfer.external_path for transfer in transfers.values()]
            if len(external_directories) != len(set(external_directories)):
                raise ValueError(
                    f"More than one operation for device {device_name} is transferring to the same folder."
                    f" This will cause data to be overwritten."
                )

        # check tile parameters
        for tile in self.config["acquisition"]["tiles"]:
            position_axes = list(tile["position_mm"].keys())
            if position_axes.sort() != self.instrument.stage_axes.sort():
                raise ValueError("not all stage axes are defined for tile positions")
            tile_channel = tile["channel"]
            if tile_channel not in self.instrument.channels:
                raise ValueError(f"channel {tile_channel} is not in {self.instrument.channels}")

    def _frame_size_mb(self, camera_id: str, writer_id: str):
        row_count_px = self.instrument.cameras[camera_id].height_px
        column_count_px = self.instrument.cameras[camera_id].width_px
        data_type = self.writers[camera_id][writer_id].data_type
        frame_size_mb = row_count_px * column_count_px * numpy.dtype(data_type).itemsize / 1024**2
        return frame_size_mb

    def _pyramid_factor(self, levels: int) -> float:
        """
        Calculates the pyramid factor for given levels.

        :param levels: The number of pyramid levels.
        :type levels: int
        :return: The pyramid factor.
        :rtype: float
        """
        pyramid_factor = 0
        for level in range(levels):
            pyramid_factor += (1 / (2**level)) ** 3
        return pyramid_factor

    def _check_compression_ratio(self, camera_id: str, writer_id: str) -> float:
        """
        Checks the compression ratio for a given camera and writer.

        :param camera_id: The ID of the camera.
        :type camera_id: str
        :param writer_id: The ID of the writer.
        :type writer_id: str
        :return: The compression ratio.
        :rtype: float
        """
        self.log.info("estimating acquisition compression ratio")
        # get the correct camera and writer
        camera = self.instrument.cameras[camera_id]
        writer = self.writers[camera_id][writer_id]
        if writer.compression != "none":
            # store initial trigger mode
            initial_trigger = camera.trigger
            # turn trigger off
            new_trigger = initial_trigger
            new_trigger["mode"] = "off"
            camera.trigger = new_trigger

            # prepare the writer
            writer.row_count_px = camera.height_px
            writer.column_count_px = camera.width_px
            writer.frame_count_px = writer.chunk_count_px
            writer.filename = "compression_ratio_test"

            chunk_size = writer.chunk_count_px
            chunk_lock = threading.Lock()
            img_buffer = SharedDoubleBuffer((chunk_size, camera.height_px, camera.width_px), dtype=writer.data_type)

            # set up and start writer and camera
            writer.prepare()
            camera.prepare()
            writer.start()
            camera.start()

            frame_index = 0
            for frame_index in range(writer.chunk_count_px):
                # grab camera frame

                current_frame = camera.grab_frame()
                # put into image buffer
                img_buffer.write_buf[frame_index] = current_frame
                frame_index += 1

            while not writer.done_reading.is_set():
                time.sleep(0.001)

            with chunk_lock:
                img_buffer.toggle_buffers()
                if writer.path is not None:
                    writer.shm_name = img_buffer.read_buf_mem_name
                    writer.done_reading.clear()

                    # close writer and camera
            writer.wait_to_finish()
            camera.stop()

            # reset the trigger
            camera.trigger = initial_trigger

            # clean up the image buffer
            img_buffer.close_and_unlink()
            del img_buffer

            # check the compressed file size
            filepath = str((writer.path / Path(f"{writer.filename}")).absolute())
            compressed_file_size_mb = os.stat(filepath).st_size / (1024**2)
            # calculate the raw file size
            frame_size_mb = self._frame_size_mb(camera_id, writer_id)
            # get pyramid factor
            pyramid_factor = self._pyramid_factor(levels=3)
            raw_file_size_mb = frame_size_mb * writer.frame_count_px * pyramid_factor
            # calculate the compression ratio
            compression_ratio = raw_file_size_mb / compressed_file_size_mb
            # delete the files
            writer.delete_files()
        else:
            compression_ratio = 1.0
        self.log.info(f"compression ratio for camera: {camera_id} writer: {writer_id} ~ {compression_ratio:.1f}")
        return compression_ratio

    def check_local_acquisition_disk_space(self) -> None:
        """
        Checks the available disk space for local acquisition.

        :raises ValueError: If there is not enough disk space.
        """
        self.log.info("checking total local storage directory space")
        drives = dict()
        for camera_id, camera in self.instrument.cameras.items():
            data_size_gb = 0
            for writer_id, writer in self.writers[camera_id].items():
                # if windows
                if platform.system() == "Windows":
                    local_drive = os.path.splitdrive(writer.path)[0]
                # if unix
                else:
                    # not completed, needs to be fixed
                    local_drive = "/"
                for tile in self.config["acquisition"]["tiles"]:
                    frame_size_mb = self._frame_size_mb(camera_id, writer_id)
                    frame_count_px = tile["steps"]
                    data_size_gb += frame_count_px * frame_size_mb / 1024
                drives.setdefault(local_drive, []).append(data_size_gb)
        for drive in drives:
            required_size_gb = sum(drives[drive])
            self.log.info(f"required disk space = {required_size_gb:.1f} [GB] on drive {drive}")
            free_size_gb = shutil.disk_usage(drive).free / 1024**3
            if data_size_gb >= free_size_gb:
                self.log.error(f"only {free_size_gb:.1f} available on drive: {drive}")
                raise ValueError(f"only {free_size_gb:.1f} available on drive: {drive}")
            else:
                self.log.info(f"available disk space = {free_size_gb:.1f} [GB] on drive {drive}")

    def check_external_acquisition_disk_space(self) -> None:
        """
        Check the total external storage directory space.

        :raises ValueError: If no transfers are configured.
        :raises ValueError: If there is not enough available disk space.
        """
        self.log.info("checking total external storage directory space")
        if self.transfers:
            drives = dict()
            for camera_id, camera in self.instrument.cameras.items():
                for transfer_id, transfer in self.transfers[camera_id].items():
                    for writer_id, writer in self.writers[camera_id].items():
                        data_size_gb = 0
                        # if windows
                        if platform.system() == "Windows":
                            external_drive = os.path.splitdrive(transfer.external_path)[0]
                        # if unix
                        else:
                            # not completed, needs to be fixed
                            external_drive = "/"
                        for tile in self.config["acquisition"]["tiles"]:
                            frame_size_mb = self._frame_size_mb(camera_id, writer_id)
                            frame_count_px = tile["steps"]
                            data_size_gb += frame_count_px * frame_size_mb / 1024
                        drives.setdefault(external_drive, []).append(data_size_gb)
            for drive in drives:
                required_size_gb = sum(drives[drive])
                self.log.info(f"required disk space = {required_size_gb:.1f} [GB] on drive {drive}")
                free_size_gb = shutil.disk_usage(drive).free / 1024**3
                if data_size_gb >= free_size_gb:
                    self.log.error(f"only {free_size_gb:.1f} available on drive: {drive}")
                    raise ValueError(f"only {free_size_gb:.1f} available on drive: {drive}")
                else:
                    self.log.info(f"available disk space = {free_size_gb:.1f} [GB] on drive {drive}")
        else:
            raise ValueError("no transfers configured. check yaml files.")

    def check_local_tile_disk_space(self, tile: dict) -> bool:
        """
        Check the local storage directory space for the next tile.

        :param tile: Tile configuration.
        :type tile: dict
        :return: True if there is enough disk space, False otherwise.
        :rtype: bool
        """
        self.log.info("checking local storage directory space for next tile")
        drives = dict()
        data_size_gb = 0
        for camera_id, camera in self.instrument.cameras.items():
            for writer_id, writer in self.writers[camera_id].items():
                # if windows
                if platform.system() == "Windows":
                    local_drive = os.path.splitdrive(writer.path)[0]
                # if unix
                else:
                    # not completed, needs to be fixed
                    local_drive = "/"
                frame_size_mb = self._frame_size_mb(camera_id, writer_id)
                frame_count_px = tile["steps"]
                data_size_gb += frame_count_px * frame_size_mb / 1024
                drives.setdefault(local_drive, []).append(data_size_gb)
        for drive in drives:
            required_size_gb = sum(drives[drive])
            self.log.info(f"required disk space = {required_size_gb:.1f} [GB] on drive {drive}")
            free_size_gb = shutil.disk_usage(drive).free / 1024**3
            if data_size_gb >= free_size_gb:
                self.log.error(f"only {free_size_gb:.1f} available on drive: {drive}")
                return False
            return True

    def check_external_tile_disk_space(self, tile: dict) -> None:
        """
        Check the external storage directory space for the next tile.

        :param tile: Tile configuration.
        :type tile: dict
        :raises ValueError: If no transfers are configured.
        :raises ValueError: If there is not enough available disk space.
        """
        self.log.info("checking external storage directory space for next tile")
        if self.transfers:
            drives = dict()
            for camera_id, camera in self.instrument.cameras.items():
                data_size_gb = 0
                # if windows
                if platform.system() == "Windows":
                    external_drive = os.path.splitdrive(self.transfers[camera_id].external_path)[0]
                # if unix
                else:
                    # not completed, needs to be fixed
                    external_drive = "/"
                frame_size_mb = self._frame_size_mb(camera_id)
                frame_count_px = tile["steps"]
                data_size_gb += frame_count_px * frame_size_mb / 1024
                drives.setdefault(external_drive, []).append(data_size_gb)
            for drive in drives:
                required_size_gb = sum(drives[drive])
                self.log.info(f"required disk space = {required_size_gb:.1f} [GB] on drive {drive}")
                free_size_gb = shutil.disk_usage(drive).free / 1024**3
                if data_size_gb >= free_size_gb:
                    self.log.error(f"only {free_size_gb:.1f} available on drive: {drive}")
                    raise ValueError(f"only {free_size_gb:.1f} available on drive: {drive}")
                else:
                    self.log.info(f"available disk space = {free_size_gb:.1f} [GB] on drive {drive}")
        else:
            raise ValueError("no transfers configured. check yaml files.")

    def check_write_speed(
        self, size: str = "16Gb", bs: str = "1M", direct: int = 1, numjobs: int = 1, iodepth: int = 1, runtime: int = 0
    ) -> None:
        """
        Check the write speed to local and external directories.

        :param size: Size of the test file, defaults to "16Gb"
        :type size: str, optional
        :param bs: Block size, defaults to "1M"
        :type bs: str, optional
        :param direct: Direct I/O flag, defaults to 1
        :type direct: int, optional
        :param numjobs: Number of jobs, defaults to 1
        :type numjobs: int, optional
        :param iodepth: I/O depth, defaults to 1
        :type iodepth: int, optional
        :param runtime: Runtime duration, defaults to 0
        :type runtime: int, optional
        :raises ValueError: If the write speed is too slow.
        """
        self.log.info("checking write speed to local and external directories")
        # windows ioengine
        if platform.system() == "Windows":
            ioengine = "windowsaio"
        # unix ioengine
        else:
            ioengine = "posixaio"

        drives = dict()
        camera_speed_mb_s = dict()

        # loop over cameras and see where they are acquiring data
        for camera_id, camera in self.instrument.cameras.items():
            for writer_id, writer in self.writers[camera_id].items():
                # check the compression ratio for this camera
                compression_ratio = self._check_compression_ratio(camera_id, writer_id)
                # grab the frame size and acquisition rate
                frame_size_mb = self._frame_size_mb(camera_id, writer_id)
                acquisition_rate_hz = self._acquisition_rate_hz
                local_path = writer.path
                # strip drive letters from paths so that we can combine
                # cameras acquiring to the same drives
                if platform.system() == "Windows":
                    local_drive_letter = os.path.splitdrive(local_path)[0]
                # if unix
                else:
                    local_drive_letter = "/"
                # add into drives dictionary append to list if same drive letter
                drives.setdefault(local_drive_letter, []).append(local_path)
                camera_speed_mb_s.setdefault(local_drive_letter, []).append(
                    acquisition_rate_hz * frame_size_mb / compression_ratio
                )
                if self.transfers:
                    for transfer_id, transfer in self.transfers[camera_id].items():
                        external_path = transfer.external_path
                        # strip drive letters from paths so that we can combine
                        # cameras acquiring to the same drives
                        if platform.system() == "Windows":
                            external_drive_letter = os.path.splitdrive(local_path)[0]
                        # if unix
                        else:
                            external_drive_letter = "/"
                        # add into drives dictionary append to list if same drive letter
                        drives.setdefault(external_drive_letter, []).append(external_path)
                        camera_speed_mb_s.setdefault(external_drive_letter, []).append(
                            acquisition_rate_hz * frame_size_mb
                        )

        for drive in drives:
            # if more than one stream on this drive, just test the first directory location
            local_path = drives[drive][0]
            test_filename = Path(f"{local_path}/iotest")
            f = open(test_filename, "a")  # Create empty file to check reading/writing speed
            f.close()
            try:
                output = subprocess.check_output(
                    rf"fio --name=test --filename={test_filename} --size={size} --rw=write --bs={bs} "
                    rf"--direct={direct} --numjobs={numjobs} --ioengine={ioengine} --iodepth={iodepth} "
                    rf"--runtime={runtime} --startdelay=0 --thread --group_reporting",
                    shell=True,
                )
                out = str(output)
                # Converting MiB to MB = (10**6/2**20)
                write_speed_mb_s = round(float(out[out.find("BW=") + len("BW=") : out.find("MiB/s")]) / (10**6 / 2**20))

                total_speed_mb_s = sum(camera_speed_mb_s[drive])
                # check if drive write speed exceeds the sum of all cameras streaming to this drive
                if write_speed_mb_s < total_speed_mb_s:
                    self.log.warning(f"write speed too slow on drive {drive}")
                    raise ValueError(f"write speed too slow on drive {drive}")

                self.log.info(f"available write speed = {write_speed_mb_s:.1f} [MB/sec] to directory {drive}")
                self.log.info(f"required write speed = {total_speed_mb_s:.1f} [MB/sec] to directory {drive}")

            except subprocess.CalledProcessError:
                self.log.warning("fio not installed on computer. Cannot verify read/write speed")
            finally:
                # Delete test file
                os.remove(test_filename)

    def check_system_memory(self) -> None:
        """
        Check the available system memory.

        :raises MemoryError: If there is not enough available system memory.
        """
        self.log.info("checking available system memory")
        # Calculate double buffer size for all channels.
        memory_gb = 0
        for camera_id, camera in self.instrument.cameras.items():
            for writer_id, writer in self.writers[camera_id].items():
                chunk_count_px = writer.chunk_count_px
                # factor of 2 for concurrent chunks being written/read
                frame_size_mb = self._frame_size_mb(camera_id, writer_id)
                memory_gb += 2 * chunk_count_px * frame_size_mb / 1024

        free_memory_gb = virtual_memory()[1] / 1024**3

        self.log.info(f"required RAM = {memory_gb:.1f} [GB]")
        self.log.info(f"available RAM = {free_memory_gb:.1f} [GB]")

        if free_memory_gb < memory_gb:
            raise MemoryError("system does not have enough memory to run")

    def check_gpu_memory(self) -> None:
        """
        Check the available GPU memory.

        :raises ValueError: If there is not enough available GPU memory.
        """
        # check GPU resources for downscaling
        memory_gb = 0
        for camera_id, camera in self.instrument.cameras.items():
            for writer_id, writer in self.writers[camera_id].items():
                chunk_count_px = writer.chunk_count_px
            # factor of 2 for concurrent chunks being written/read
            frame_size_mb = self._frame_size_mb(camera_id, writer_id)
            memory_gb += 2 * chunk_count_px * frame_size_mb / 1024
        # should we use something other than gputools to check?
        total_gpu_memory_gb = get_device().get_info("MAX_MEM_ALLOC_SIZE") / 1024**3
        self.log.info(f"required GPU RAM = {memory_gb:.1f} [GB]")
        self.log.info(f"available GPU RAM = {total_gpu_memory_gb:.1f} [GB]")
        if memory_gb >= total_gpu_memory_gb:
            raise ValueError(f"{memory_gb} [GB] GPU RAM requested but only {total_gpu_memory_gb} [GB] available")
