import logging
from abc import abstractmethod
from collections.abc import Callable

import numpy as np


class BaseDownSample:
    """
    Base class for image downsampling.
    """

    def __init__(self, binning: int) -> None:
        """
        Module for handling downsampling processes.

        :param binning: The binning factor for downsampling.
        :type binning: int
        """
        self._binning = binning
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @abstractmethod
    def run(self, method: Callable[[np.ndarray], np.ndarray], image: np.ndarray) -> np.ndarray:
        """
        Run function for image downsampling.

        :param method: The downsampling method to use.
        :type method: Callable[[numpy.ndarray], numpy.ndarray]
        :param image: Input image
        :type image: numpy.ndarray
        :return: Downsampled image
        :rtype: numpy.ndarray
        """
