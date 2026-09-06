from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

from invariant.errors import InvariantError


class LiteralDumper(yaml.SafeDumper):
    pass


class ConfigDumper(LiteralDumper):
    pass


class ConfigLoader(yaml.SafeLoader):
    pass


_BOOL_TAG = "tag:yaml.org,2002:bool"
_TRUE_FALSE = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


def _yaml_12_boolean_resolvers(resolvers: dict[object, list[tuple[str, object]]]):
    return {
        key: [(tag, pattern) for tag, pattern in values if tag != _BOOL_TAG]
        for key, values in resolvers.items()
    }


ConfigLoader.yaml_implicit_resolvers = _yaml_12_boolean_resolvers(
    yaml.SafeLoader.yaml_implicit_resolvers
)
ConfigDumper.yaml_implicit_resolvers = _yaml_12_boolean_resolvers(
    yaml.SafeDumper.yaml_implicit_resolvers
)
ConfigLoader.add_implicit_resolver(_BOOL_TAG, _TRUE_FALSE, list("tTfF"))
ConfigDumper.add_implicit_resolver(_BOOL_TAG, _TRUE_FALSE, list("tTfF"))


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.Node:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


LiteralDumper.add_representer(str, _represent_string)
ConfigDumper.add_representer(str, _represent_string)


def load_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except FileNotFoundError:
        raise InvariantError(f"Invariant: no such file '{path}'", code="missing_file") from None
    except yaml.YAMLError as exc:
        raise InvariantError(
            f"Invariant: invalid YAML in {path}: {exc}", code="invalid_yaml"
        ) from exc


def load_config_yaml(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.load(handle, Loader=ConfigLoader)
    except FileNotFoundError:
        raise InvariantError(f"Invariant: no such file '{path}'", code="missing_file") from None
    except yaml.YAMLError as exc:
        raise InvariantError(
            f"Invariant: invalid YAML in {path}: {exc}", code="invalid_yaml"
        ) from exc


def parse_config_yaml(text: str) -> Any:
    return yaml.load(text, Loader=ConfigLoader)


def dump_yaml(path: Path, value: Any) -> None:
    _dump(path, value, LiteralDumper)


def dump_config_yaml(path: Path, value: Any) -> None:
    _dump(path, value, ConfigDumper)


def _dump(path: Path, value: Any, dumper: type[yaml.SafeDumper]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, pending_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    pending = Path(pending_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.dump(
                value,
                handle,
                Dumper=dumper,
                sort_keys=False,
                allow_unicode=True,
                width=100,
            )
        pending.replace(path)
    finally:
        if pending.exists():
            pending.unlink()
