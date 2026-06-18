"""
Build an ``aind-data-schema`` v2 :class:`Instrument` from a live ExASPIM instrument.

This module is the single source of truth for translating voxel-style device
descriptors (the ``instrument.config["instrument"]["devices"]`` YAML payload plus
the corresponding live device objects) into ``aind_data_schema`` v2.8.1 components.

It is intentionally decoupled from :mod:`exaspim_control.metadata_launch` so the
device-mapping logic can be tested in isolation, and it imports nothing that
depends on the ``voxel`` runtime.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Callable, Iterator

from aind_data_schema.components.coordinates import Axis, CoordinateSystem
from aind_data_schema.components.devices import (
    Camera,
    DAQDevice,
    Detector,
    Device,
    Filter,
    Laser,
    MotorizedStage,
    Objective,
    ScanningStage,
)
from aind_data_schema.core.instrument import Instrument
from aind_data_schema_models.coordinates import AxisName, Direction, Origin
from aind_data_schema_models.devices import (
    DataInterface,
    DetectorType,
    FilterType,
    ImmersionMedium,
    StageAxisDirection,
)
from aind_data_schema_models.modalities import Modality
from aind_data_schema_models.organizations import Organization
from aind_data_schema_models.units import SizeUnit

if TYPE_CHECKING:  # pragma: no cover - type-only imports avoid voxel at runtime
    from exaspim_control.exa_spim_instrument import ExASPIM


# ---------------------------------------------------------------------------
# Direction map (mirrors metadata_launch._DIRECTION_MAP). Duplicated here so
# this module has no dependency back on metadata_launch.
# ---------------------------------------------------------------------------
_DIRECTION_MAP: dict[str, Direction] = {
    "Anterior to Posterior": Direction.AP,
    "Anterior_to_posterior": Direction.AP,
    "Posterior to Anterior": Direction.PA,
    "Posterior_to_anterior": Direction.PA,
    "Inferior to Superior": Direction.IS,
    "Inferior_to_superior": Direction.IS,
    "Superior to Inferior": Direction.SI,
    "Superior_to_inferior": Direction.SI,
    "Left to Right": Direction.LR,
    "Left_to_right": Direction.LR,
    "Right to Left": Direction.RL,
    "Right_to_left": Direction.RL,
}


# ---------------------------------------------------------------------------
# Manufacturer inference. Driver paths in voxel YAML follow the pattern
# ``voxel.devices.<category>.<vendor>[.<submodule>]`` so we map the ``vendor``
# token to an :class:`Organization`. Fallback is ``Organization.OTHER``.
# ---------------------------------------------------------------------------
_VENDOR_TOKEN_TO_ORG: dict[str, Organization] = {
    "oxxius": Organization.from_name("Oxxius"),
    "asi": Organization.from_name("Applied Scientific Instrumentation"),
    "vieworks": Organization.from_name("Vieworks"),
    "thorlabs": Organization.from_name("Thorlabs"),
    "ni": Organization.from_name("National Instruments"),
    "national_instruments": Organization.from_name("National Instruments"),
}


def _resolve_organization(driver_or_name: Any) -> Organization:
    """Map a voxel driver path or vendor name to an :class:`Organization`.

    Parameters
    ----------
    driver_or_name : Any
        The voxel ``driver`` string (e.g. ``"voxel.devices.laser.oxxius.lbx"``) or
        a free-form vendor name (e.g. ``"Oxxius"``).

    Returns
    -------
    Organization
        The matching organization, or :attr:`Organization.OTHER` if no match.
    """
    if not driver_or_name:
        return Organization.OTHER
    text = str(driver_or_name).lower()
    for token, org in _VENDOR_TOKEN_TO_ORG.items():
        if token in text:
            return org
    # Allow callers to pass a literal organization name as a last resort.
    looked_up = Organization.from_name(str(driver_or_name))
    return looked_up if looked_up is not None else Organization.OTHER


_PRIMITIVES: tuple[type, ...] = (int, float, str, bool, bytes)


def _attr(obj: Any, name: str) -> Any:
    """Return ``obj.name`` only if it is a primitive value; otherwise ``None``.

    Guards against ``unittest.mock.MagicMock`` (and similar dynamic objects) auto-creating
    attributes that look truthy but cannot be coerced into schema fields.
    """
    value = getattr(obj, name, None)
    if isinstance(value, _PRIMITIVES) and not isinstance(value, bool):
        return value
    if isinstance(value, bool):
        return value
    return None


# ---------------------------------------------------------------------------
# Device walking
# ---------------------------------------------------------------------------
def _walk_devices(devices_yaml: dict[str, Any]) -> Iterator[tuple[str, str, dict[str, Any]]]:
    """Yield ``(name, voxel_type, spec)`` for every device, recursing one level into ``subdevices``.

    Controllers in the voxel YAML wrap lasers/stages under ``subdevices``; we hoist those
    to the top level so the resulting Instrument exposes them as first-class components.
    The controller itself is still yielded so callers can decide whether to keep it.
    """
    for name, spec in devices_yaml.items():
        spec = spec or {}
        voxel_type = str(spec.get("type", "unknown"))
        yield name, voxel_type, spec
        for sub_name, sub_spec in (spec.get("subdevices") or {}).items():
            sub_spec = sub_spec or {}
            yield sub_name, str(sub_spec.get("type", "unknown")), sub_spec


def _common_kwargs(name: str, voxel_device: Any, spec: dict[str, Any]) -> dict[str, Any]:
    """Pull common :class:`Device` fields from a live voxel object + YAML spec.

    Mining order: live object attributes (primitives only) → YAML ``init`` block → defaults.
    """
    init = spec.get("init") or {}
    serial_number = (
        _attr(voxel_device, "serial_number")
        or init.get("serial_number")
        or init.get("id")
    )
    manufacturer = _resolve_organization(spec.get("driver"))
    model = (
        _attr(voxel_device, "model")
        or spec.get("module")
        or init.get("model")
    )
    return {
        "name": name,
        "serial_number": str(serial_number) if serial_number is not None else None,
        "manufacturer": manufacturer,
        "model": str(model) if model is not None else None,
    }


# ---------------------------------------------------------------------------
# Coordinate system (shared between Acquisition and Instrument JSONs)
# ---------------------------------------------------------------------------
def _to_direction(value: Any) -> Direction | None:
    """Coerce a GUI string or :class:`Direction` enum into a :class:`Direction`."""
    if value is None:
        return None
    if isinstance(value, Direction):
        return value
    return _DIRECTION_MAP.get(str(value)) or Direction(str(value))


def _build_coordinate_system(metadata: Any, *, system_name: str = "ExASPIM-XYZ") -> CoordinateSystem:
    """Build the v2 :class:`CoordinateSystem` from anatomical-direction metadata.

    Preserves the original ExASPIM v0.x convention: the X axis pulls from
    ``y_anatomical_direction`` and the Y axis from ``x_anatomical_direction``.
    """
    return CoordinateSystem(
        name=system_name,
        origin=Origin.ORIGIN,
        axes=[
            Axis(name=AxisName.X, direction=_to_direction(getattr(metadata, "y_anatomical_direction", None))),
            Axis(name=AxisName.Y, direction=_to_direction(getattr(metadata, "x_anatomical_direction", None))),
            Axis(name=AxisName.Z, direction=_to_direction(getattr(metadata, "z_anatomical_direction", None))),
        ],
        axis_unit=SizeUnit.UM,
    )


# ---------------------------------------------------------------------------
# Per-device builders
# ---------------------------------------------------------------------------
def _build_camera(name: str, device: Any, spec: dict[str, Any]) -> Camera:
    """Build a :class:`Camera` from a voxel camera device + YAML spec."""
    properties = spec.get("properties") or {}
    sensor_width = _attr(device, "sensor_width_px") or properties.get("sensor_width_px")
    sensor_height = _attr(device, "sensor_height_px") or properties.get("sensor_height_px")
    return Camera(
        **_common_kwargs(name, device, spec),
        detector_type=DetectorType.CAMERA,
        data_interface=DataInterface.OTHER,
        sensor_width=int(sensor_width) if sensor_width is not None else None,
        sensor_height=int(sensor_height) if sensor_height is not None else None,
        notes="data_interface inferred as Other; refine when available.",
    )


def _build_laser(name: str, device: Any, spec: dict[str, Any]) -> Laser:
    """Build a :class:`Laser` from a voxel laser device + YAML spec."""
    init = spec.get("init") or {}
    wavelength = _attr(device, "wavelength") or init.get("wavelength")
    if wavelength is None:
        # Last-resort: try to parse the device name (e.g., "639 nm").
        for token in str(name).split():
            if token.isdigit():
                wavelength = int(token)
                break
    common = _common_kwargs(name, device, spec)
    # Laser requires an explicit Manufacturer (not None and not OTHER without notes).
    notes_parts: list[str] = []
    if common["manufacturer"] == Organization.OTHER:
        notes_parts.append("Manufacturer inferred as Other.")
    return Laser(
        **common,
        wavelength=int(wavelength) if wavelength is not None else 0,
        notes=" ".join(notes_parts) or None,
    )


def _build_scanning_stage(name: str, device: Any, spec: dict[str, Any]) -> ScanningStage:
    """Build a :class:`ScanningStage` from a voxel scanning stage."""
    init = spec.get("init") or {}
    instrument_axis = str(init.get("instrument_axis", "z")).upper()
    axis_name = AxisName(instrument_axis) if instrument_axis in {a.value for a in AxisName} else AxisName.Z
    travel = _attr(device, "travel_mm") or 50
    return ScanningStage(
        **_common_kwargs(name, device, spec),
        travel=travel,
        stage_axis_direction=StageAxisDirection.DETECTION_AXIS,
        stage_axis_name=axis_name,
    )


def _build_motorized_stage(name: str, device: Any, spec: dict[str, Any]) -> MotorizedStage:
    """Build a :class:`MotorizedStage` for tiling/focusing stages."""
    travel = _attr(device, "travel_mm") or 50
    return MotorizedStage(
        **_common_kwargs(name, device, spec),
        travel=travel,
    )


def _build_filter(name: str, device: Any, spec: dict[str, Any]) -> Filter:
    """Build a :class:`Filter` (default to band pass)."""
    common = _common_kwargs(name, device, spec)
    return Filter(
        **common,
        filter_type=FilterType.BANDPASS,
    )


def _build_daq(name: str, device: Any, spec: dict[str, Any]) -> DAQDevice:
    """Build a :class:`DAQDevice` from a voxel DAQ description."""
    common = _common_kwargs(name, device, spec)
    if common["manufacturer"] == Organization.OTHER:
        common["manufacturer"] = Organization.from_name("National Instruments")
    return DAQDevice(
        **common,
        data_interface=DataInterface.PCIE,
    )


def _build_objective(name: str, device: Any, spec: dict[str, Any]) -> Objective:
    """Build an :class:`Objective` from a voxel objective entry (fields must be present)."""
    init = spec.get("init") or {}
    return Objective(
        **_common_kwargs(name, device, spec),
        numerical_aperture=_attr(device, "numerical_aperture") or init.get("numerical_aperture", 0.305),
        magnification=_attr(device, "magnification") or init.get("magnification", 5),
        immersion=ImmersionMedium(init.get("immersion", "oil")),
    )


def _build_generic(name: str, device: Any, spec: dict[str, Any], voxel_type: str) -> Device:
    """Fallback: emit a generic :class:`Device` carrying a notes line for the voxel type."""
    common = _common_kwargs(name, device, spec)
    return Device(
        **common,
        notes=f"voxel type: {voxel_type}",
    )


_DISPATCH: dict[str, Callable[[str, Any, dict[str, Any]], Any]] = {
    "camera": _build_camera,
    "laser": _build_laser,
    "scanning_stage": _build_scanning_stage,
    "tiling_stage": _build_motorized_stage,
    "focusing_stage": _build_motorized_stage,
    "filter": _build_filter,
    "daq": _build_daq,
    "objective": _build_objective,
}


# ---------------------------------------------------------------------------
# Synthetic objective (SPIM modality requires one)
# ---------------------------------------------------------------------------
_SYNTHETIC_OBJECTIVE_NOTES = (
    "Placeholder objective synthesized to satisfy SPIM modality validation; "
    "supply an 'objective' device in the instrument YAML to override."
)


def _build_default_objective() -> Objective:
    """Return a synthetic :class:`Objective` used when no objective is configured."""
    return Objective(
        name="exaspim-objective",
        manufacturer=Organization.OTHER,
        numerical_aperture=0.305,
        magnification=5,
        immersion=ImmersionMedium.OIL,
        notes=_SYNTHETIC_OBJECTIVE_NOTES,
    )


# ---------------------------------------------------------------------------
# Modification date helper
# ---------------------------------------------------------------------------
def _coerce_date(value: Any) -> date:
    """Coerce a :class:`date`, :class:`datetime`, or ISO-format string to :class:`date`."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value.split("T", 1)[0])
        except ValueError:
            pass
    return date.today()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _voxel_device(instrument: "ExASPIM | Any", voxel_type: str, name: str) -> Any:
    """Look up a live voxel device on ``instrument`` by its voxel type and name."""
    plural = {
        "camera": "cameras",
        "laser": "lasers",
        "scanning_stage": "scanning_stages",
        "tiling_stage": "tiling_stages",
        "focusing_stage": "focusing_stages",
        "filter": "filters",
        "daq": "daqs",
        "flip_mount": "flip_mounts",
        "indicator_light": "indicator_lights",
        "objective": "objectives",
        "tunable_lens": "tunable_lenses",
        "filter_wheel": "filter_wheels",
        "controller": "controllers",
    }.get(voxel_type)
    if plural is None:
        return None
    container = getattr(instrument, plural, None) or {}
    return container.get(name)


def build_instrument(
    instrument: "ExASPIM | Any",
    metadata: Any,
    *,
    modalities: list[Modality] | None = None,
    coordinate_system: CoordinateSystem | None = None,
) -> Instrument:
    """Build a v2.8.1 :class:`Instrument` from an ExASPIM instrument and its metadata.

    Parameters
    ----------
    instrument : ExASPIM
        The live ExASPIM instrument; its ``config['instrument']['devices']`` payload is
        walked to discover devices, and live device objects are mined for attributes.
    metadata : Any
        The :class:`AINDMetadataClass` (or compatible) object exposing ``instrument_id``,
        anatomical-direction strings, and optional ``modification_date``/``location``/``notes``.
    modalities : list[Modality], optional
        Override modalities. Defaults to ``[Modality.SPIM]``.
    coordinate_system : CoordinateSystem, optional
        Reuse an existing coordinate system (e.g., from the matching ``Acquisition``) so
        the two JSON files agree. Built from ``metadata`` if not supplied.

    Returns
    -------
    Instrument
        A populated v2.8.1 :class:`Instrument` model.
    """
    devices_yaml: dict[str, Any] = (
        instrument.config.get("instrument", {}).get("devices", {}) or {}
    )

    components: list[Any] = []
    seen_names: set[str] = set()
    for name, voxel_type, spec in _walk_devices(devices_yaml):
        if name in seen_names:
            continue
        device = _voxel_device(instrument, voxel_type, name)
        builder = _DISPATCH.get(voxel_type)
        if builder is None:
            component = _build_generic(name, device, spec, voxel_type)
        else:
            component = builder(name, device, spec)
        components.append(component)
        seen_names.add(name)

    # SPIM modality requires an Objective component; synthesize a placeholder if absent.
    if not any(isinstance(c, Objective) for c in components):
        components.append(_build_default_objective())

    # SPIM modality also requires at least one Detector and ScanningStage, which the
    # walker emits naturally for the canonical ExASPIM YAML.
    _ = Detector  # imported for mypy/type-checker; required to keep import live

    instrument_id = _attr(metadata, "instrument_id") or instrument.config.get("instrument", {}).get(
        "id", "unknown-instrument"
    )

    return Instrument(
        instrument_id=str(instrument_id),
        modification_date=_coerce_date(getattr(metadata, "modification_date", None)),
        modalities=list(modalities or [Modality.SPIM]),
        coordinate_system=coordinate_system or _build_coordinate_system(metadata),
        location=_attr(metadata, "location"),
        temperature_control=_attr(metadata, "temperature_control"),
        notes=_attr(metadata, "notes"),
        components=components,
    )
