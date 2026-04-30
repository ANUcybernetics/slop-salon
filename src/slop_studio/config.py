"""Parse and represent slop_studio.toml configuration."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Agent:
    name: str
    handle: str
    github_repo: str
    sprite_id: str = ""
    siblings: list[str] = field(default_factory=list)


@dataclass
class Config:
    path: Path
    agents: dict[str, Agent]


def load_config(path: Path | str = "slop_studio.toml") -> Config:
    """Parse slop_studio.toml and return a Config."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    with p.open("rb") as f:
        data = tomllib.load(f)

    agents = {}
    for name, fields in data.get("agents", {}).items():
        agents[name] = Agent(
            name=name,
            handle=fields["handle"],
            github_repo=fields["github_repo"],
            sprite_id=fields.get("sprite_id", ""),
            siblings=list(fields.get("siblings", [])),
        )
    return Config(path=p, agents=agents)


def save_sprite_id(config: Config, agent_name: str, sprite_id: str) -> None:
    """Update slop_studio.toml in place to record a freshly-provisioned sprite ID."""
    text = config.path.read_text()
    pattern = re.compile(
        rf"(\[agents\.{re.escape(agent_name)}\][^\[]*sprite_id\s*=\s*)\"[^\"]*\"",
        re.DOTALL,
    )
    new_text, n = pattern.subn(rf'\1"{sprite_id}"', text)
    if n != 1:
        raise ValueError(
            f"could not find sprite_id field for [agents.{agent_name}] in {config.path}"
        )
    config.path.write_text(new_text)
