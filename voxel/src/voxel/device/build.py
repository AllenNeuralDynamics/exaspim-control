import copy
import importlib
import logging
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("builder")

BuildErrorType = Literal["import", "instantiation", "dependency", "circular", "unknown"]


class BuildConfig(BaseModel):
    target: str
    init: dict[str, Any] = Field(default_factory=dict)
    defaults: dict[str, Any] | None = None


type BuildGroupSpec = dict[str, BuildConfig]


class BuildError(BaseModel):
    uid: str
    error_type: BuildErrorType
    traceback: str | None


class FailedDependencyError(RuntimeError):
    def __init__(self, owner_uid: str, dep_uid: str):
        super().__init__(f"Dependency {dep_uid} failed to build (referenced by {owner_uid})")
        self.owner_uid = owner_uid
        self.dep_uid = dep_uid


def get_build_cls(cfg: BuildConfig):
    target = cfg.target
    module_path, class_name = target.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


@dataclass
class BuildContext:
    """State for building a graph of objects from configs."""

    configs: Mapping[str, BuildConfig]
    built: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, BuildError] = field(default_factory=dict)
    building: set[str] = field(default_factory=set)  # for circular detection

    def __post_init__(self):
        self._done: bool = False
        self.log = logging.getLogger("object_builder")

    def build(self):
        if self._done:
            self.log.debug("BuildContext.build() called again; nothing to do.")
            return
        for uid in self.configs:
            if uid not in self.built and uid not in self.errors:
                self._build_one(uid)
        self._done = True

    def _build_one(self, uid: str) -> Any | BuildError:  # noqa: PLR0911
        """Build one object, recursively building its dependencies first."""
        if uid in self.built:
            return self.built[uid]

        if uid in self.errors:
            return self.errors[uid]

        if uid in self.building:
            self.errors[uid] = BuildError(
                uid=uid, error_type="circular", traceback=f"Circular dependency detected for object: {uid}"
            )
            return self.errors[uid]

        self.building.add(uid)
        try:
            cfg = self.configs[uid]

            # 1. Build dependencies
            dep_error = self._build_dependencies(uid)
            if dep_error is not None:
                self.errors[uid] = dep_error
                return dep_error

            # 2. Import class
            try:
                cls = get_build_cls(cfg)
            except Exception:
                self.errors[uid] = BuildError(
                    uid=uid or cfg.target,
                    error_type="import",
                    traceback=traceback.format_exc(),
                )
                return self.errors[uid]

            # 3. Build
            try:
                resolved_init = self._resolve_init(uid, copy.deepcopy(cfg.init) or {})
                resolved_init["uid"] = uid
                obj = cls(**resolved_init)
                defaults = cfg.defaults or {}
                for name, value in defaults.items():
                    try:
                        setattr(obj, name, value)
                    except Exception:
                        self.log.warning(f"Failed to set property {name} for {uid}: {traceback.format_exc()}")
                self.built[uid] = obj
                return self.built[uid]
            except FailedDependencyError as e:
                self.errors[uid] = BuildError(
                    uid=uid,
                    error_type="dependency",
                    traceback=f"Dependency {e.dep_uid} failed to build",
                )
                return self.errors[uid]
            except Exception:
                self.errors[uid] = BuildError(uid=uid, error_type="instantiation", traceback=traceback.format_exc())
                return self.errors[uid]

        except Exception:
            err = BuildError(
                uid=uid,
                error_type="unknown",
                traceback=traceback.format_exc(),
            )
            self.errors[uid] = err
            return err

        finally:
            self.building.discard(uid)

    # --- private helpers -------------------------------------------------

    def _build_dependencies(self, uid: str) -> BuildError | None:
        """
        Build all dependencies for the given uid. Returns a BuildError if any
        dependency fails, otherwise None.
        """

        def _extract_dependencies(uid: str) -> set[str]:
            """
            Scan init params for strings that match other config keys.
            """
            cfg = self.configs[uid]
            deps: set[str] = set()
            init_params = cfg.init or {}

            def scan(v: Any) -> None:
                if isinstance(v, str):
                    if v in self.configs and v != uid:
                        deps.add(v)
                elif isinstance(v, dict):
                    for vv in v.values():
                        scan(vv)
                elif isinstance(v, list):
                    for item in v:
                        scan(item)

            scan(init_params)
            return deps

        for dep_uid in _extract_dependencies(uid):
            self._build_one(dep_uid)
            if dep_uid in self.errors:
                return BuildError(
                    uid=uid,
                    error_type="dependency",
                    traceback=f"Dependency {dep_uid} failed to build",
                )
        return None

    def _resolve_init(self, owner_uid: str, value: Any) -> Any:
        """Recursively replace string uids with built objects, if available."""
        if isinstance(value, str):
            if value in self.built:
                return self.built[value]
            if value in self.errors:
                # hard fail: this is a dependency failure
                raise FailedDependencyError(owner_uid, value)
            return value

        if isinstance(value, dict):
            return {k: self._resolve_init(owner_uid, v) for k, v in value.items()}

        if isinstance(value, list):
            return [self._resolve_init(owner_uid, v) for v in value]

        return value


def build_objects(configs: Mapping[str, BuildConfig]) -> tuple[dict[str, Any], dict[str, BuildError]]:
    """
    Build all objects in `configs` with dependency resolution.
    """
    ctx = BuildContext(configs=configs)
    ctx.build()
    return ctx.built, ctx.errors


def build_object(cfg: BuildConfig):
    cls = get_build_cls(cfg)
    obj = cls(**cfg.init)
    if cfg.defaults:
        for name, value in cfg.defaults.items():
            try:
                setattr(obj, name, value)
            except Exception:
                logger.warning(f"Failed to set property {name} for {cls.__name__}: {traceback.format_exc()}")
    return obj
