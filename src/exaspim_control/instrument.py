from voxel.instrument import Instrument


class ExASPIM(Instrument):
    """
    Class for handling ExASPIM instrument configuration and verification.
    """

    def _verify_instrument(self) -> list[str]:
        """
        Verify the ExASPIM instrument configuration.

        :raises ValueError: If the number of scanning stages is not 1
        :raises ValueError: If the number of cameras is not 1
        :raises ValueError: If the number of DAQs is not 1
        :raises ValueError: If there are no lasers
        :raises ValueError: If the x tiling stage is not defined
        :raises ValueError: If the y tiling stage is not defined
        """
        # assert that only one scanning stage is allowed
        self.log.info("verifying instrument configuration")

        errors: list[str] = []
        if (num_scanning_stages := len(self.scanning_stages)) != 1:
            errors.append(f"one scanning stage must be defined but {num_scanning_stages} detected")

        if (num_cameras := len(self.cameras)) != 1:
            errors.append(f"one camera must be defined but {num_cameras} detected")

        if (num_daqs := len(self.daqs)) != 1:
            errors.append(f"one daq must be defined but {num_daqs} detected")

        if (num_lasers := len(self.lasers)) < 1:
            errors.append(f"at least one laser is required but {num_lasers} detected")

        if not self.tiling_stages["x"]:
            errors.append("x tiling stage is required")

        if not self.tiling_stages["y"]:
            errors.append("y tiling stage is required")

        return errors
