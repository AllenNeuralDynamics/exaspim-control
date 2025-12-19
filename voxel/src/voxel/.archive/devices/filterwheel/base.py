from voxel.devices.axes.discrete import VoxelDiscreteAxis

# class VoxelFilterWheel(VoxelDevice):
#     """
#     Base class for filter wheel devices.
#     """

#     @property
#     @abstractmethod
#     def filter(self) -> str:
#         """
#         Get the current filter.

#         :return: Current filter name
#         :rtype: str
#         """

#     @filter.setter
#     @abstractmethod
#     def filter(self, filter_name: str) -> None:
#         """
#         Set the current filter.

#         :param filter_name: Filter name
#         :type filter_name: str
#         """

#     @abstractmethod
#     def close(self) -> None:
#         """
#         Close the filter wheel device.
#         """


class VoxelFilterWheel(VoxelDiscreteAxis): ...
