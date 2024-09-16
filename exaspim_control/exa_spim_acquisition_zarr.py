import time
from pathlib import Path
from threading import Event
from voxel.instruments.instrument import Instrument
from voxel.acquisition.acquisition import Acquisition
import inflection

DIRECTORY = Path(__file__).parent.resolve()

class ExASPIMAcquisition(Acquisition):

    def __init__(self, instrument: Instrument, config_filename: str, log_level='INFO'):

        super().__init__(instrument, DIRECTORY / Path(config_filename), log_level)

        # verify acquisition
        self._verify_acquisition()

        # initialize threads
        self.acquisition_threads = dict()
        self.transfer_threads = dict()
        self.stop_engine = Event()  # Event to flag a stop in engine

    def _setup_operation(self, device: object, settings: dict):
        """Overwrite so metadata class can pass in acquisition_name to devices that require it"""

        super()._setup_operation(device, settings)

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
                    chunk_size = writer.chunk_size_z_px
                else:
                    if writer.chunk_size_z_px != chunk_size:
                        raise ValueError (f'Chunk sizes of writers must all be {chunk_size}')
        self.chunk_count_px = chunk_size  # define chunk size to be used later in acquisiiton

    def run(self):
        """Run function for exaspim"""

        super().run()

        filenames = dict()
        # initialize transfer threads
        self.transfer_threads = {}

        for tile in self.config['acquisition']['tiles']:

            # check local disk space and run if enough disk space
            if self.check_local_tile_disk_space(tile) is True:

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
                        chunk_count_px = writer.chunk_size_z_px
                        tile_count_px = tile['steps']
                        if tile_count_px < chunk_count_px:
                            raise ValueError(f'tile frame count {tile_count_px} \
                                is less than chunk size = {chunk_count_px} px')

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
                    # TODO remember this is hardcoded as acquire key
                    writer = self.writers[camera_id]['acquire']
                    self.engine(tile, filename, camera, writer)
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

    def engine(self, tile, filename, camera, writer):

        # setup writers
        writer.frame_count_px = tile['steps']
        writer.row_count_px = camera.height_px
        writer.column_count_px = camera.width_px
        writer.x_voxel_size_um = 0.748  # TODO pull this from instrument yaml
        writer.y_voxel_size_um = 0.748  # TODO pull this from instrument yaml
        writer.filename = filename

        # set up writer
        writer.prepare()
        writer.start(frame_count=tile['steps'])

        for daq_id, daq in self.instrument.daqs.items():
            self.log.info(f'starting daq {daq_id}')
            for task in [daq.ao_task, daq.do_task, daq.co_task]:
                if task is not None:
                    task.start()

        frames_collected = 0
        while frames_collected < writer.frame_count_px-1:
            with camera.runtime.get_available_data(0) as data:
                packet = data.get_frame_count()
                frames_collected += packet
                if packet != 0:
                    self.log.info(f"id: {camera.id}, frame: {frames_collected}")
            
        camera.stop()

    def stop_acquisition(self):
        """Overwriting to better stop acquisition"""

        self.stop_engine.set()
        for thread in self.acquisition_threads.values():
            thread.join()
        # TODO: Stop any devices here? or stop transfer_threads?
        raise RuntimeError
