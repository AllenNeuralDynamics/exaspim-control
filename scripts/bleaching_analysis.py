# import h5py
# import hdf5plugin
# import numpy as np
# import tifffile
# import matplotlib.pyplot as plt

# directories = [
#     # "D:\\Galvo Bleaching Experiment\\2025-07-21_16-52_Cy3B-galvo\\exaSPIM\\",
#     # "D:\\Galvo Bleaching Experiment\\2025-07-21_16-13_AF568-1-galvo\\exaSPIM\\",
#     # "D:\\Galvo Bleaching Experiment\\2025-07-21_17-20_AF488-galvo\\exaSPIM\\",
#     "D:\\Galvo Bleaching Experiment\\2025-07-21_17-48_AF647-galvo\\exaSPIM\\"
# ]

# file_prefixes = [
#     # "Cy3B_galvo",
#     # "AF568_galvo",
#     # "AF488_galvo",
#     "AF647_galvo"
# ]

# tiles = 2

# lower_threshold = [
#     1000
# ]

# upper_threshold = [
#     5000
# ]

# # percentile_50 = np.zeros(shape=(len(directories), tiles), dtype=np.float32)
# # percentile_75 = np.zeros(shape=(len(directories), tiles), dtype=np.float32)
# # percentile_90 = np.zeros(shape=(len(directories), tiles), dtype=np.float32)
# # percentile_95 = np.zeros(shape=(len(directories), tiles), dtype=np.float32)
# # percentile_99 = np.zeros(shape=(len(directories), tiles), dtype=np.float32)
# ratio = np.zeros(shape=(len(directories), tiles), dtype=np.float32)

# idx = 0
# for directory in directories:
#     for tile_index in range(0, tiles):
#         file_path = f"{directory}{file_prefixes[idx]}_{tile_index:06d}_ch_639.ims"
#         file_handle = h5py.File(file_path, "r")
#         dataset = file_handle["DataSet"]["ResolutionLevel 4"]["TimePoint 0"]["Channel 0"]["Data"]
#         data = dataset[:, :, :]
#         tifffile.imwrite(f"D:\\{file_prefixes[idx]}_{tile_index:06d}_ch_561.tiff", data.max(axis=0))
#         data = data.flatten().astype(np.float32)
#         data = data - 37
#         if tile_index == 0:
#             greater_mask = data > lower_threshold[idx]
#             less_mask = data < upper_threshold[idx]
#             mask = greater_mask & less_mask
#         # percentile_50[idx, tile_index]=np.nanpercentile(data[mask], 50)
#         # percentile_75[idx, tile_index]=np.nanpercentile(data[mask], 75)
#         # percentile_90[idx, tile_index]=np.nanpercentile(data[mask], 90)
#         # percentile_95[idx, tile_index]=np.nanpercentile(data[mask], 95)
#         # percentile_99[idx, tile_index]=np.nanpercentile(data[mask], 99)
#         if tile_index == 0:
#             first_values = data[mask]
#         temp_ratio = np.divide(data[mask], first_values)
#         ratio[idx, tile_index] = np.mean(temp_ratio[:])

#     # percentile_50 = percentile_50 / np.max(percentile_50)
#     # percentile_75 = percentile_75 / np.max(percentile_75)
#     # percentile_90 = percentile_90 / np.max(percentile_90)
#     # percentile_99 = percentile_99 / np.max(percentile_99)

#     # np.savetxt(f"{file_prefixes[idx]}_percentile_50.csv", percentile_50, delimiter=",")
#     # np.savetxt(f"{file_prefixes[idx]}_percentile_75.csv", percentile_75, delimiter=",")
#     # np.savetxt(f"{file_prefixes[idx]}_percentile_90.csv", percentile_90, delimiter=",")
#     # np.savetxt(f"{file_prefixes[idx]}_percentile_95.csv", percentile_95, delimiter=",")
#     # np.savetxt(f"{file_prefixes[idx]}_percentile_99.csv", percentile_99, delimiter=",")
#     np.savetxt(f"{file_prefixes[idx]}_ratio.csv", ratio, delimiter=",")

#     idx += 1
