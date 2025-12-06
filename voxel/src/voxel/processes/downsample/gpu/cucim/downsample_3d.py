import cupy
import numpy as np
from cucim.skimsage.transform import downscale_local_mean
from voxel.processes.downsample.base import BaseDownSample


class CucimDownSample3D(BaseDownSample):
    """
    Voxel 3D downsampling with cucim.
    """

    def __init__(self, binning: int) -> None:
        """
        Module for handling 3D downsampling processes.

        :param binning: The binning factor for downsampling.
        :type binning: int
        :raises ValueError: If the binning factor is not valid.
        """
        super().__init__(binning)

    def run(self, image: np.array) -> np.ndarray:
        """
        Run function for image downsampling.

        :param image: Input image
        :type image: numpy.array
        :return: Downsampled image
        :rtype: numpy.array
        """
        # convert numpy to cupy array
        image = cupy.asarray(image)
        return downscale_local_mean(image, factors=(self._binning, self._binning, self._binning))
