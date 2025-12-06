"""exa-spim-control repository."""

import warnings

# Suppress PyOpenCL compiler warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pyopencl")
