import numpy
import time
from ruamel.yaml import YAML
from pathlib import Path
from threading import Event, Thread, Lock
from multiprocessing.shared_memory import SharedMemory
from voxel.instruments.instrument import Instrument
from voxel.writers.data_structures.shared_double_buffer import SharedDoubleBuffer
from voxel.acquisition.acquisition import Acquisition
import inflection
import math

DIRECTORY = Path(__file__).parent.resolve()

class ExASPIMAcquisition(Acquisition):

    def __init__(self, instrument: Instrument, config_filename: str, yaml_handler: YAML, log_level='INFO'):

        super().__init__(instrument, DIRECTORY / Path(config_filename), yaml_handler, log_level)

        # verify acquisition
        self._verify_acquisition()

        # initialize threads
        self.acquisition_threads = dict()
        self.transfer_threads = dict()
        self.stop_engine = Event()  # Event to flag a stop in engine

    def _setup_class(self, device: object, settings: dict):
        """Overwrite so metadata class can pass in acquisition_name to devices that require it"""

        super()._setup_class(device, settings)

        # set acquisition_name attribute if it exists for object
        if hasattr(device, 'acquisition_name'):
            setattr(device, 'acquisition_name', self.metadata.acquisition_name)

    def _verify_acquisition(self):
        """Check that chunk sizes are the same for all writers"""
        super()._verify_acquisition()

        chunk_size = None
        for device in self.writers.values():
            for writer in device.values():
                if chunk_size is None:
                    chunk_size = writer.chunk_count_px
                else:
                    if writer.chunk_count_px != chunk_size:
                        raise ValueError (f'Chunk sizes of writers must all be {chunk_size}')
        self.chunk_count_px = chunk_size  # define chunk size to be used later in acquisiiton

    def run(self):
        """Run function for exaspim"""

        try:
            super().run()

            filenames = dict()
            # initialize transfer threads
            self.transfer_threads = {}

            for tile in self.config['acquisition']['tiles']:
                # check local disk space and run if enough disk space
                if self.check_local_tile_disk_space(tile):

                    tile_num = tile['tile_number']
                    tile_channel = tile['channel']
                    filename_prefix = tile['prefix']

                    # build filenames dict for all devices
                    for device_name, device_specs in self.instrument.config['instrument']['devices'].items():
                        device_type = device_specs['type']
                        filenames[device_name] = f'{filename_prefix}_{tile_num:06}_' \
                                                 f'ch_{tile_channel}_{device_type}_{device_name}'
                    # sanity check length of scan
                    for writer_dictionary in self.writers.values():
                        for writer in writer_dictionary.values():
                            chunk_count_px = writer.chunk_count_px
                            tile_count_px = tile['steps']
                            if tile_count_px < chunk_count_px:
                                raise ValueError(f'tile frame count {tile_count_px} \
                                    is less than chunk size = {writer.chunk_count_px} px')

                    # move all tiling stages to correct positions
                    for tiling_stage_id, tiling_stage in self.instrument.tiling_stages.items():
                        # grab stage axis letter
                        instrument_axis = tiling_stage.instrument_axis
                        tile_position = tile['position_mm'][instrument_axis]
                        self.log.info(f'moving stage {tiling_stage_id} to {instrument_axis} = {tile_position} mm')
                        tiling_stage.move_absolute_mm(tile_position, wait=False)

                    # wait on all stages... simultaneously
                    for tiling_stage_id, tiling_stage in self.instrument.tiling_stages.items():
                        while tiling_stage.is_axis_moving():
                            instrument_axis = tiling_stage.instrument_axis
                            tile_position = tile['position_mm'][instrument_axis]
                            self.log.info(
                                f'waiting for stage {tiling_stage_id}: {instrument_axis} = {tiling_stage.position_mm} -> {tile_position} mm')
                            time.sleep(1.0)

                    # prepare the scanning stage for step and shoot behavior
                    for scanning_stage_id, scanning_stage in self.instrument.scanning_stages.items():
                        self.log.info(f'setting up scanning stage: {scanning_stage_id}')
                        # grab stage axis letter
                        instrument_axis = scanning_stage.instrument_axis
                        tile_position = tile['position_mm'][instrument_axis]
                        backlash_removal_position = tile_position - 0.01
                        self.log.info(f'moving stage {scanning_stage_id} to {instrument_axis} = {backlash_removal_position} mm')
                        scanning_stage.move_absolute_mm(tile_position - 0.01, wait=False)
                        self.log.info(f'moving stage {scanning_stage_id} to {instrument_axis} = {tile_position} mm')
                        scanning_stage.move_absolute_mm(tile_position, wait=False)
                        self.log.info(f'backlash on {scanning_stage_id} removed')
                        step_size_um = tile['step_size']
                        self.log.info(f'setting step shoot scan step size to {step_size_um} um')
                        scanning_stage.setup_step_shoot_scan(step_size_um)

                    for scanning_stage_id, scanning_stage in self.instrument.scanning_stages.items():
                        while scanning_stage.is_axis_moving():
                            instrument_axis = scanning_stage.instrument_axis
                            tile_position = tile['position_mm'][instrument_axis]
                            self.log.info(
                                f'waiting for stage {scanning_stage_id}: {instrument_axis} = {scanning_stage.position_mm} -> {tile_position} mm')
                            time.sleep(1.0)

                    # setup channel i.e. laser and filter wheels
                    self.log.info(f'setting up channel: {tile_channel}')
                    channel = self.instrument.channels[tile_channel]
                    for device_type, devices in channel.items():
                        for device_name in devices:
                            device = getattr(self.instrument, device_type)[device_name]
                            if device_type in ['lasers', 'filters']:
                                device.enable()
                            for setting, value in tile.get(device_name, {}).items():
                                # NEED TO CHECK HERE THAT FOCUSING STAGE POSITION GETS SET
                                setattr(device, setting, value)
                                self.log.info(f'setting {setting} for {device_type} {device_name} to {value}')

                    # THIS PROBABLY SHOULD GET SET ABOVE?
                    # setup camera binning
                    for camera_id, camera in self.instrument.cameras.items():
                        binning = tile[camera_id]['binning']
                        self.log.info(f'setting {camera_id} binning to {binning}')
                        camera.binning = binning

                    for daq_name, daq in self.instrument.daqs.items():
                        if daq.tasks.get('ao_task', None) is not None:
                            daq.add_task('ao')
                            daq.generate_waveforms('ao', tile_channel)
                            daq.write_ao_waveforms()
                        if daq.tasks.get('do_task', None) is not None:
                            daq.add_task('do')
                            daq.generate_waveforms('do', tile_channel)
                            daq.write_do_waveforms()
                        if daq.tasks.get('co_task', None) is not None:
                            pulse_count = self.chunk_count_px
                            daq.add_task('co', pulse_count)

                    # run any pre-routines for all devices
                    for device_name, routine_dictionary in getattr(self, 'routines', {}).items():
                        device_type = self.instrument.config['instrument']['devices'][device_name]['type']
                        self.log.info(f'running routines for {device_type} {device_name}')
                        for routine_name, routine in routine_dictionary.items():
                            # TODO: how to figure out what to pass in routines for different devices.
                            # config seems like a good place but what about arguments generated in the acquisition?
                            # make it a rule that routines must have filename property? And need to pass in device to start?
                            device_object = getattr(self.instrument, inflection.pluralize(device_type))[device_name]
                            routine.filename = filenames[device_name] + '_' + routine_name
                            routine.start(device=device_object)

                    # setup camera, data writing engines, and processes
                    for camera_id, camera in self.instrument.cameras.items():
                        self.log.info(f'arming camera and writer for {camera_id}')
                        # pass in camera specific camera, writer, and processes
                        # a filename must exist for each camera
                        filename = filenames[camera_id]
                        # a writer must exist for each camera
                        writer = self.writers[camera_id]
                        # check if any processes exist, they may not exist
                        processes = {} if not hasattr(self, 'processes') else self.processes[camera_id]

                        self.engine(tile, filename, camera, writer, processes)
                        self.log.info(f'starting camera and writer for {camera_id}')

                    # stop the daq
                    for daq_id, daq in self.instrument.daqs.items():
                        self.log.info(f'stopping daq {daq_id}')
                        daq.stop()

                    # create and start transfer threads from previous tile
                    for device_name, transfer_dict in getattr(self, 'transfers', {}).items():
                        self.transfer_threads[device_name] = {}
                        for transfer_name, transfer in transfer_dict.items():
                            self.transfer_threads[device_name][tile_num] = transfer
                            self.transfer_threads[device_name][tile_num].filename = filenames[device_name]
                            self.log.info(f"starting file transfer for {device_name} and tile {tile_num}")
                            self.transfer_threads[device_name][tile_num].start()

                # if not enough local disk space, but file transfers are running
                # wait for them to finish, because this will free up disk space
                elif len(self.transfer_threads) != 0:
                    # check if any transfer threads are still running, if so wait on them
                    for device_name, transfer_dict in self.transfer_threads.items():
                        for tile_num, transfer_thread in transfer_dict.items():
                            self.log.info(f"checking on file transfer for {device_name} and tile {tile_num}")
                            if transfer_thread.is_alive():
                                self.log.info(f"waiting on file transfer for {device_name} and tile {tile_num}")
                                transfer_thread.wait_until_finished()
                                self.log.info(f"deleting file transfer for {device_name} and tile {tile_num}")
                                del self.transfer_threads[device_name][tile_num]
                            else:
                                # delete from transfer thread dictionary
                                self.log.info(f"deleting file transfer for {device_name} and tile {tile_num}")
                                del self.transfer_threads[device_name][tile_num]
                # otherwise this is the first tile and there is simply not enough disk space
                # for the first tile
                else:
                    raise ValueError(f"not enough local disk space")

            # wait for last tiles file transfer
            # TODO: We seem to do this logic a lot of looping through device then op.
            # Should this be a function?
            for device_name, transfer_dict in getattr(self, 'transfers', {}).items():
                for transfer_id, transfer_thread in transfer_dict.items():
                    if transfer_thread.is_alive():
                        self.log.info(f"waiting on file transfer for {device_name} {transfer_id}")
                        transfer_thread.wait_until_finished()
        finally:
            if getattr(self, 'transfers', {}) != {}:  # save to external paths
                # save acquisition config
                for device_name, transfer_dict in getattr(self, 'transfers', {}).items():
                    for transfer in transfer_dict.values():
                        self.update_current_state_config()
                        self.save_config(Path(transfer.external_path, transfer.acquisition_name)/'acquisition_config.yaml')

                # save instrument config
                for device_name, transfer_dict in getattr(self, 'transfers', {}).items():
                    for transfer in transfer_dict.values():
                        self.instrument.update_current_state_config()
                        self.instrument.save_config(Path(transfer.external_path, transfer.acquisition_name)/'instrument_config.yaml')

            else: # no transfers so save locally
                # save acquisition config
                for device_name, writer_dict in self.writers.items():
                    for writer in writer_dict.values():
                        self.update_current_state_config()
                        self.save_config(Path(writer.local_path, writer.acquisition_name)/'acquisition_config.yaml')

                # save instrument config
                for device_name, writer_dict in self.writers.items():
                    for writer in writer_dict.values():
                        self.instrument.update_current_state_config()
                        self.instrument.save_config(Path(writer.local_path, writer.acquisition_name)/'instrument_config.yaml')

    def engine(self, tile, filename, camera, writers, processes):

        chunk_locks = {}
        img_buffers = {}

        # setup writers
        for writer_name, writer in writers.items():
            writer.row_count_px = camera.height_px // camera.binning
            writer.column_count_px = camera.width_px // camera.binning
            writer.frame_count_px = tile['steps']
            writer.x_pos_mm = tile['position_mm']['x']
            writer.y_pos_mm = tile['position_mm']['y']
            writer.z_pos_mm = tile['position_mm']['z']
            writer.x_voxel_size_um = 0.748 * camera.binning  # TODO pull this from instrument yaml
            writer.y_voxel_size_um = 0.748 * camera.binning # TODO pull this from instrument yaml
            writer.z_voxel_size_um = tile['step_size']
            writer.filename = filename
            writer.channel = tile['channel']

            chunk_locks[writer_name] = Lock()
            img_buffers[writer_name] = SharedDoubleBuffer(
                (writer.chunk_count_px, camera.height_px // camera.binning, camera.width_px // camera.binning),
                dtype=writer.data_type)

        # setup processes
        process_buffers = {}
        for process_name, process in processes.items():
            process.row_count_px = camera.height_px // camera.binning
            process.column_count_px = camera.width_px // camera.binning
            process.frame_count_px = tile['steps']
            process.filename = filename
            img_bytes = numpy.prod(camera.height_px // camera.binning * camera.width_px // camera.binning) * numpy.dtype(
                process.data_type).itemsize
            buffer = SharedMemory(create=True, size=int(img_bytes))
            process_buffers[process_name] = buffer
            process.buffer_image = numpy.ndarray((camera.height_px // camera.binning, camera.width_px // camera.binning),
                                                 dtype=process.data_type, buffer=buffer.buf)
            process.prepare(buffer.name)

        # set up writer and camera
        camera.prepare()
        for writer in writers.values():
            writer.prepare()
            writer.start()
        # pause for 1 sec to get writer set up
        time.sleep(1)
        camera.start()
        for process in processes.values():
            process.start()

        frame_index = 0
        last_frame_index = tile['steps'] - 1

        chunk_count = math.ceil(tile['steps'] / self.chunk_count_px)
        remainder = tile['steps'] % self.chunk_count_px
        last_chunk_size = self.chunk_count_px if not remainder else remainder

        # Images arrive serialized in repeating channel order.
        for stack_index in range(tile['steps']):
            if self.stop_engine.is_set():
                break
            chunk_index = stack_index % self.chunk_count_px
            # Start a batch of pulses to generate more frames and movements.
            if chunk_index == 0:
                chunks_filled = math.floor(stack_index / self.chunk_count_px)
                remaining_chunks = chunk_count - chunks_filled
                # num_pulses = last_chunk_size if remaining_chunks == 1 else self.chunk_count_px
                # for daq_name, daq in self.instrument.daqs.items():
                    # daq.co_task.timing.cfg_implicit_timing(sample_mode= AcqType.FINITE,
                    #                                         samps_per_chan= num_pulses)
                    #################### IMPORTANT ####################
                    # for the exaspim, the NIDAQ is the master, so we start this last
                for daq_id, daq in self.instrument.daqs.items():
                    self.log.info(f'starting daq {daq_id}')
                    for task in [daq.ao_task, daq.do_task, daq.co_task]:
                        if task is not None:
                            task.start()

            # Grab camera frame
            current_frame = camera.grab_frame()
            camera.signal_acquisition_state()
            # TODO: Update writer variables?
            # writer.signal_progress_percent
            for img_buffer in img_buffers.values():
                img_buffer.add_image(current_frame)

            # Dispatch either a full chunk of frames or the last chunk,
            # which may not be a multiple of the chunk size.
            if chunk_index + 1 == self.chunk_count_px or stack_index == last_frame_index:
                for daq_name, daq in self.instrument.daqs.items():
                    daq.stop()
                while not writer.done_reading.is_set() and not self.stop_engine.is_set():
                    time.sleep(0.001)
                for writer_name, writer in writers.items():
                    # Dispatch chunk to each StackWriter compression process.
                    # Toggle double buffer to continue writing images.
                    # To read the new data, the StackWriter needs the name of
                    # the current read memory location and a trigger to start.
                    # Lock out the buffer before toggling it such that we
                    # don't provide an image from a place that hasn't been
                    # written yet.
                    with chunk_locks[writer_name]:
                        img_buffers[writer_name].toggle_buffers()
                        if writer.path is not None:
                            writer.shm_name = \
                                img_buffers[writer_name].read_buf_mem_name
                            writer.done_reading.clear()

            # check on processes
            for process in processes.values():
                while process.new_image.is_set():
                    time.sleep(0.1)
                process.buffer_image[:, :] = current_frame
                process.new_image.set()

            frame_index += 1

        camera.stop()

        for writer in writers.values():
            writer.wait_to_finish()

        for process in processes.values():
            process.wait_to_finish()
            # process.close()

        # clean up the image buffer
        self.log.debug(f"deallocating shared double buffer.")
        for img_buffer in img_buffers.values():
            img_buffer.close_and_unlink()
            del img_buffer
        for buffer in process_buffers.values():
            buffer.close()
            buffer.unlink()
            del buffer

    def stop_acquisition(self):
        """Overwriting to better stop acquisition"""

        self.stop_engine.set()
        for thread in self.acquisition_threads.values():
            thread.join()

        # TODO: Stop any devices here? or stop transfer_threads?

        raise RuntimeError
