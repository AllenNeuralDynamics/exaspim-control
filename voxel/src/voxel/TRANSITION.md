# New vs Classic Voxel Module Analysis

This document compares the new voxel module (`voxel/new/`) with the classic devices module (`voxel/devices/`) and provides recommendations for completing the new API.

## 1. Architectural Improvements in New Module

### Base Device (`new/device/base.py` vs `devices/base.py`)

| Aspect | Classic | New |
|--------|---------|-----|
| Base class | `VoxelDevice(ABC)` - 28 lines | `Device[T: StrEnum]` - 465 lines |
| Metadata | None | Rich `@describe()` decorator for label, desc, units, stream |
| Introspection | None | `PropertyInfo`, `CommandInfo`, `DeviceInterface` classes |
| Validation | None | Pydantic-based `Command` wrapper with auto-validation |
| Type hints | Basic | Full generics, `ClassVar`, `Self` |
| Serialization | None | Built-in JSON export via `CommandResponse`, `PropsResponse` |

**Key improvement:** The new module provides a full self-describing API with automatic parameter validation, making devices introspectable and suitable for remote/RPC control.

### Property System (`new/device/props/`)

**New features not in classic:**

- `deliminated_float/int`: Bounded numeric properties with min/max/step constraints and automatic clamping
- `enumerated_string/int`: Constrained choice properties
- `PropertyModel`: Serializable property representation with constraints
- Dynamic bounds via callables (e.g., `max_value=lambda self: self._max_power_mw`)

---

## 2. Device Type Comparison

### DAQ (`SpimDaq` vs `VoxelDAQ`)

| Aspect | Classic | New |
|--------|---------|-----|
| Base | `VoxelDAQ` extends `VoxelDevice` | `SpimDaq` extends `SpimDevice` |
| Task creation | `create_task()` + manual `add_ao_channel()` | `create_ao_task(name, pins)` - channels auto-added |
| Task types | Single `DaqTaskInst` for all | Separate `AOTask`, `COTask` protocols |
| Task tracking | Manual tracking | `active_tasks` property, auto-cleanup on `close()` |
| Pin management | Manual assign/release | Auto-release on `close_task()` |
| Pulse helper | `pulse()` method on DAQ | `pulse()` standalone function in `utils.py` |
| CO tasks | `create_co_pulse_task()` | `create_co_task()` with typed `COTask` return |

**New DAQ API Design:**

The new DAQ uses a factory method pattern with typed task protocols:

```python
# Create AO task - channels are added automatically
task = daq.create_ao_task("galvo", pins=["ao0", "ao1"])
task.cfg_samp_clk_timing(rate=10000, sample_mode=AcqSampleMode.FINITE, samps_per_chan=1000)
task.write(waveform_data)
task.start()
task.wait_until_done(timeout=2.0)
daq.close_task("galvo")  # Pins released automatically

# Create CO task for clock generation
clock = daq.create_co_task("clock", counter="ctr0", frequency_hz=1000, output_pin="PFI0")
clock.start()
daq.close_task("clock")

# Simple pulse utility
from voxel.interfaces.daq import pulse
pulse(daq, pin="ao5", duration_s=0.1, voltage_v=5.0)
```

**Key improvements over classic:**

- Type-safe task protocols (`AOTask`, `COTask`) instead of generic `DaqTaskInst`
- Factory methods handle channel setup - no manual `add_ao_channel()` calls
- Automatic pin cleanup when tasks are closed
- `active_tasks` property for introspection
- `close()` method closes all tasks automatically

---

### Camera (`SpimCamera` vs `BaseCamera`)

| Aspect | Classic | New |
|--------|---------|-----|
| ROI | 4 separate properties (`width_px`, `height_px`, `width_offset_px`, `height_offset_px`) | Single `ROI` NamedTuple with `ROIConstraints` and alignment policy |
| Pixel format | `pixel_type: str` | `PixelFormat` Literal + `Dtype` enum integration |
| Size info | `sensor_width_px`, `sensor_height_px` | `Vec2D[int] sensor_size_px` |
| Stream state | `acquisition_state() -> dict` | `stream_info -> StreamInfo | None` typed model |
| Trigger | `trigger: str` property | `TriggerMode`, `TriggerPolarity` enums with explicit methods |
| Temperature | 2 props (`mainboard_temperature_c`, `sensor_temperature_c`) | Not included |
| Methods | `reset()`, `abort()` | Not included |

**Recommendation:** The new camera is **significantly improved** with:

- Proper ROI handling with constraints and coercion policies
- Type-safe pixel formats
- Typed stream info

**Missing from new:**

- `reset()`, `abort()` methods
- Temperature properties (may be intentional)
- `line_interval_us`, `readout_mode` properties

---

### Laser (`SpimLaser` vs `BaseLaser`)

| Aspect | Classic | New |
|--------|---------|-----|
| Wavelength | Readonly abstract property | Constructor param + readonly property |
| Power bounds | None | `deliminated_float()` with dynamic bounds |
| Metadata | None | Full `@describe()` annotations with `stream=True` for reactive properties |

**Recommendation:** New laser interface is **better** - adds bounds validation and streaming support. Both have equivalent core functionality.

---

### Axes

| Aspect | Classic | New |
|--------|---------|-----|
| Continuous | `VoxelAxis` | `ContinuousAxis` + `BaseAxis` |
| Discrete | `VoxelDiscreteAxis` | `DiscreteAxis` |
| Slot keys | `Mapping[int, str \| None]` | `Mapping[int \| str, str \| None]` (better YAML compat) |
| Metadata | None | Full `@describe()` annotations |
| Home method | Default impl calls `move(min(slots))` | Abstract - must be implemented |

**Recommendation:** New is **improved**. The `home()` being abstract in new is better - the default behavior in classic can cause unintended moves at init.

---

### FilterWheel

| Classic | New |
|---------|-----|
| `VoxelFilterWheel(VoxelDiscreteAxis)` - empty alias | No dedicated type - uses `DiscreteAxis` directly |

**Recommendation:** Consistent with new design - filterwheel is just a discrete axis with no additional interface.

---

## 3. Missing Device Types in New Module

Devices in **classic but NOT in new**:

| Device Type | Classic Location | Status | Notes |
|-------------|-----------------|--------|-----|
| Joystick | `devices/joystick/base.py` | Missing | Need to decide how to implement this. Classic way seems confusing. |
| Rotation Mount | `devices/rotation_mount/base.py` | Missing | can be composed from discrete or continuous axis |
| Tunable Lens | `devices/tunable_lens/base.py` | Missing | important for SPIM focusing, should implement but might consider a general api with voicecoil and similar devices |
| Temperature Sensor | `devices/temperature_sensor/base.py` | Missing | need to decide how to deal with 'sensor' devices in general |
| Power Meter | `devices/power_meter/base.py` | Missing | useful for calibration workflows but should decide how to deal with 'sensor' devices in general |
| Indicator Light | `devices/indicator_light/base.py` | Missing | decide if this is worth being a high level device |
| Flip Mount | `devices/flip_mount/base.py` | Missing | just use discrete axis? |
| Stage | `devices/stage/base.py` | Missing (though axes can compose) | not needed as separate device if axes can compose |

---

## 4. New Devices Only in New Module

| Device Type | Location |
|-------------|----------|
| AOTF | `new/interfaces/aotf/base.py` |

The AOTF interface is **well-designed** with channel registration, collision detection, and multiple laser integration patterns (shuttered vs modulated).

---

## 5. Driver Implementations Comparison

### NI DAQ

| Classic `devices/daq/ni.py` | New `drivers/daqs/ni.py` |
|----------------------------|--------------------------|
| 402 lines | ~600 lines (includes typed task classes) |
| `NiDAQTaskWrapper` generic wrapper | `NiAOTask`, `NiCOTask` separate typed classes |
| `_NiCOTaskWrapper` for counters | `NiCOTask` with full `COTask` protocol |
| Manual task tracking | `_active_tasks` dict with auto-cleanup |
| `create_co_pulse_task()` returns name | `create_co_task()` returns typed `COTask` |

### Vieworks Camera

New implementation (`drivers/cameras/egrabber/vieworks.py`) is **complete** with proper ROI, constrained properties, and streaming. Uses the new `deliminated_float`/`enumerated_int` decorators.

### TigerHub

Both modules have full TigerHub implementations with protocol parser, ops modules, and model classes. Structure is identical.

---

## 6. exaSPIM Transition Status

This section tracks progress toward transitioning `exaspim_control` from `voxel/devices/` to `voxel/new/`.

### Devices Required by exaspim.yaml (beta3)

| Device | Old Target | New Driver | Status |
|--------|-----------|------------|--------|
| **vp-151mx** (Camera) | `voxel.devices.camera.vieworks.egrabber.VieworksCamera` | `voxel.drivers.cameras.egrabber.vieworks.VieworksCamera` | ✅ Ready |
| **pcie-6738** (DAQ) | `voxel.devices.daq.ni.NiDaq` | `voxel.drivers.daqs.ni.NiDaq` | ✅ Ready |
| **filter_wheel_main** | `voxel.devices.filterwheel.ni.DAQFilterWheel` | `voxel.drivers.axes.daq_filter_wheel.DAQFilterWheel` | 🔴 **BLOCKING** (to create) |
| **488-nm, 639-nm** (Lasers) | `voxel.devices.laser.coherent.genesis_mx.GenesisMXLaser` | `voxel.drivers.lasers.coherent.genesis_mx.GenesisMXLaser` | ✅ Ready |
| **tigerhub** (Controller) | `voxel.devices.controller.tigerhub.TigerHub` | `voxel.drivers.tigerhub.hub.TigerHub` | ✅ Ready |
| **x/y/z/theta-axis, focus axes** | `voxel.devices.axes.asi.TigerAxis` | `voxel.drivers.axes.asi.TigerAxis` | ✅ Ready |

### Supporting Types Status

| Type | Old Location | New Location | Status |
|------|-------------|--------------|--------|
| `AcqSampleMode` | `voxel.devices.daq.base` | `voxel.interfaces.daq` | ✅ Ready |
| `PinInfo` | `voxel.devices.daq.base` | `voxel.interfaces.daq` | ✅ Ready |
| `TaskStatus` | `voxel.devices.daq.base` | `voxel.interfaces.daq` | ✅ Ready |
| `Frequency, Time, Voltage` | `voxel.devices.daq.quantity` | `voxel.device.quantity` | ✅ Ready |
| `NormalizedRange, VoltageRange` | `voxel.devices.daq.quantity` | `voxel.device.quantity` | ✅ Ready |
| `Waveform` (all types) | `voxel.devices.daq.wave` | `voxel.interfaces.daq.wave` | ✅ Ready |

### exaspim_control Files Requiring Updates

| File | Old Imports | New Imports | Status |
|------|-------------|-------------|--------|
| `acq_task.py` | `VoxelDAQ`, `AcqSampleMode`, `PinInfo`, etc. | Use `acq_task_new.py` instead | ✅ `acq_task_new.py` created |
| `acq_task_new.py` | Still uses `voxel.devices.daq.quantity/wave` | Update to `voxel.*` | 🟡 Needs import fix |
| `instrument.py` | All old base classes | New interfaces | 🔴 Needs rewrite |
| `background_collection.py` | `BaseCamera` | `SpimCamera` | 🟡 Simple change |
| `qtgui/acq_task_widget.py` | `TaskStatus` (TYPE_CHECKING) | `voxel.interfaces.daq.TaskStatus` | 🟡 Simple change |
| `qtgui/devices/axis_widget.py` | `VoxelAxis` (TYPE_CHECKING) | `ContinuousAxis` | 🟡 Simple change |
| `qtgui/devices/camera_widget.py` | `BaseCamera` (TYPE_CHECKING) | `SpimCamera` | 🟡 Simple change |
| `qtgui/devices/filter_wheel_widget.py` | `VoxelFilterWheel` | `DiscreteAxis` | 🟡 Simple change |
| `qtgui/devices/laser_widget.py` | `BaseLaser` | `SpimLaser` | 🟡 Simple change |

### Transition Checklist

**Phase 1: Create Missing Drivers** (BLOCKING)
- [ ] Create `voxel/new/drivers/axes/daq_filter_wheel.py` implementing `DiscreteAxis`

**Phase 2: Update acq_task_new.py Imports**
- [ ] Change `from voxel.devices.daq.quantity import ...` → `from voxel.device.quantity import ...`
- [ ] Change `from voxel.devices.daq.wave import Waveform` → `from voxel.interfaces.daq.wave import Waveform`

**Phase 3: Update instrument.py**
- [ ] Replace `VoxelDevice` with `SpimDevice`
- [ ] Replace `BaseCamera` with `SpimCamera`
- [ ] Replace `BaseLaser` with `SpimLaser`
- [ ] Replace `VoxelAxis` with `ContinuousAxis`
- [ ] Replace `VoxelFilterWheel` with `DiscreteAxis`
- [ ] Replace `VoxelDAQ` with `SpimDaq`
- [ ] Remove `BaseFlipMount`, `BaseJoystick` (not used in exaspim.yaml)

**Phase 4: Update UI Widgets**
- [ ] Update type hints in all `qtgui/devices/*.py` files
- [ ] Update `background_collection.py`

**Phase 5: Update exaspim.yaml Targets**
- [ ] Change all `voxel.devices.*` targets to `voxel.drivers.*`

---

## 7. Summary Recommendations

### DAQ

- [x] **Add task management methods** to `SpimDaq`: `create_ao_task()`, `create_co_task()`, `close_task()`, etc.
- [x] **Add `pulse()` helper** for simple output operations (standalone function in `utils.py`)
- [x] **Add typed task protocols**: `AOTask`, `COTask`, `DaqTask` in `tasks.py`
- [x] **Create `acq_task_new.py`** using the new DAQ API
- [ ] **Update `acq_task_new.py` imports** to use new quantity/waveform locations

#### DAQ Migration Notes for exaspim_control

The `acq_task` module in exaspim_control needs to be updated to use the new DAQ API:

**Before (old API):**
```python
task_inst = daq.get_task_inst("acq_task")
pin_info = daq.assign_pin("acq_task", "ao0")
task_inst.add_ao_channel(pin_info.path, "ao0_channel")
task_inst.cfg_samp_clk_timing(...)
task_inst.write(data)
task_inst.start()
# ...
task_inst.stop()
task_inst.close()
daq.release_pins_for_task("acq_task")
```

**After (new API):**
```python
task = daq.create_ao_task("acq_task", pins=["ao0"])
task.cfg_samp_clk_timing(...)
task.write(data)
task.start()
# ...
daq.close_task("acq_task")  # Handles stop, close, and pin release
```

Key changes:
- Replace `get_task_inst()` + `assign_pin()` + `add_ao_channel()` with single `create_ao_task()`
- Replace manual `stop()` + `close()` + `release_pins_for_task()` with `close_task()`
- Task objects are now typed (`AOTask` or `COTask`) with appropriate methods
- Counter output uses `create_co_task()` instead of `create_co_pulse_task()`

### Filter Wheel

- [ ] **Create `DAQFilterWheel` driver** in `voxel/new/drivers/axes/daq_filter_wheel.py` implementing `DiscreteAxis`
  - Must support NI DAQ pulse-based position control
  - Reference: `voxel/devices/filterwheel/ni.py`

### Camera

- [ ] Consider adding `reset()` and `abort()` methods
- [ ] Temperature properties could be added if needed for hardware monitoring

### Axes

- Current design is good. Keep `home()` abstract to prevent unintended device moves.

### Missing Devices (Not Blocking exaSPIM)

Priority order for implementing missing interfaces:

1. **Flip Mount** - simple discrete axis, used in beam paths (not in exaspim.yaml)
2. **Tunable Lens** - critical for SPIM focusing (not in exaspim.yaml)
3. **Joystick** - useful for manual control integration (not in exaspim.yaml)
4. **Power Meter** - useful for calibration workflows (not in exaspim.yaml)
5. Others (rotation mount, temp sensor, indicator light) - lower priority

### General

- The new module's property descriptors and introspection are **significant improvements**
- The `stream=True` flag on properties enables reactive UI patterns
- The Protocol-based abstractions are more flexible than ABCs for duck-typing
