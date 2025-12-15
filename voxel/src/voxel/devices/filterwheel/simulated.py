import logging
import time

from voxel.devices.filterwheel.base import VoxelFilterWheel

FILTERS = []

SWITCH_TIME_S = 0.1  # estimated timing


class SimulatedFilterWheel(VoxelFilterWheel):
    """
    FilterWheel class for handling simulated filter wheel devices.
    """

    def __init__(self, uid: str, filters: dict[str, int]) -> None:
        super().__init__(uid=uid)
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        self.id = uid
        self.filters = filters
        for filter in filters:
            FILTERS.append(filter)
        # force homing of the wheel to first position
        self.filter = FILTERS[0]

    @property
    def filter(self) -> str:
        """
        Get the current filter.

        :return: Current filter name
        :rtype: str
        """
        return self._filter

    @filter.setter
    def filter(self, filter_name: str) -> None:
        """
        Set the current filter.

        :param filter_name: Filter name
        :type filter_name: str
        """
        self.log.info(f"setting filter to {filter_name}")
        if filter_name not in FILTERS:
            msg = f"Filter {filter_name} not in filter list: {FILTERS}"
            raise ValueError(msg)
        self._filter = filter_name
        time.sleep(SWITCH_TIME_S)

    def close(self):
        """
        Close the filter wheel device.
        """
