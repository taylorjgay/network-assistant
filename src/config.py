import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ER605Config:
    host: str
    username: str
    password: str


@dataclass
class DecoConfig:
    host: str
    password: str


@dataclass
class PiholeConfig:
    host: str
    api_token: str


@dataclass
class Config:
    er605: ER605Config
    deco: DecoConfig
    pihole: PiholeConfig


def load_config(path: Path | str | None = None) -> Config:
    if path is None:
        path = Path(__file__).parent.parent / "config.json"
    with open(path) as f:
        data = json.load(f)
    return Config(
        er605=ER605Config(**data["er605"]),
        deco=DecoConfig(**data["deco"]),
        pihole=PiholeConfig(**data["pihole"]),
    )
