"""Parse and represent slop_salon.toml configuration."""

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
    namesake: str = ""
    namesake_url: str = ""


@dataclass
class Config:
    path: Path
    agents: dict[str, Agent]


def load_config(path: Path | str = "slop_salon.toml") -> Config:
    """Parse slop_salon.toml and return a Config."""
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
            namesake=fields.get("namesake", ""),
            namesake_url=fields.get("namesake_url", ""),
        )
    return Config(path=p, agents=agents)


def save_sprite_id(config: Config, agent_name: str, sprite_id: str) -> None:
    """Update slop_salon.toml in place to record a freshly-provisioned sprite ID.

    If the agent block already has a `sprite_id = "..."` line, that value is
    replaced. If not, a new line is appended immediately after the
    `[agents.<name>]` header.
    """
    text = config.path.read_text()
    replace_pattern = re.compile(
        rf"(\[agents\.{re.escape(agent_name)}\][^\[]*sprite_id\s*=\s*)\"[^\"]*\"",
        re.DOTALL,
    )
    new_text, n = replace_pattern.subn(rf'\1"{sprite_id}"', text)
    if n == 1:
        config.path.write_text(new_text)
        return

    # No existing sprite_id field; append after the agent header.
    insert_pattern = re.compile(rf"(\[agents\.{re.escape(agent_name)}\]\n)")
    new_text, n = insert_pattern.subn(rf'\1sprite_id = "{sprite_id}"\n', text)
    if n != 1:
        raise ValueError(f"could not find [agents.{agent_name}] section in {config.path}")
    config.path.write_text(new_text)
