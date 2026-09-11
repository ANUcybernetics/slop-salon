"""Parse and represent slop_salon.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

AUTH_MODES = ("connector", "secret_env", "credentials")


@dataclass(frozen=True)
class Provider:
    """Where an agent's thinking comes from: an endpoint, a model, an auth mode.

    `connector` sends a placeholder token that the sprites.dev gateway
    overrides with the org's stored key. `secret_env` names the admin-side env
    var `slop wake` passes as the bearer token at tick time. `credentials` is
    reserved for a subscription OAuth profile and is not implemented.
    """

    name: str
    base_url: str
    model: str
    auth: str = "connector"
    secret_env: str = ""
    context_window: int = 0

    @property
    def model_id(self) -> str:
        """The model without its OpenRouter preset suffix --- the provenance stamp."""
        return self.model.split("@", 1)[0]


@dataclass(frozen=True)
class Salon:
    """The agents that know of each other, and the model they share."""

    name: str
    label: str = ""
    provider: str = ""


@dataclass(frozen=True)
class Soul:
    name: str
    label: str = ""


@dataclass
class Agent:
    name: str
    handle: str
    github_repo: str
    sprite_id: str = ""
    salon: str = ""
    soul: str = ""
    # Every other agent in the salon, in registry order. Derived, never listed.
    siblings: list[str] = field(default_factory=list)
    namesake: str = ""
    namesake_url: str = ""
    live: bool = False
    # Provider override, or "" to take the salon's, then the registry default.
    provider: str = ""


@dataclass
class Config:
    path: Path
    agents: dict[str, Agent]
    providers: dict[str, Provider] = field(default_factory=dict)
    salons: dict[str, Salon] = field(default_factory=dict)
    souls: dict[str, Soul] = field(default_factory=dict)
    default_provider: str = ""
    claude_version: str = ""

    def provider_for(self, agent_name: str) -> Provider:
        """The agent's own `provider`, then its salon's, then `default_provider`."""
        agent = self.agents[agent_name]
        salon_provider = self.salons[agent.salon].provider if agent.salon else ""
        chosen = agent.provider or salon_provider or self.default_provider
        if not chosen:
            raise ValueError(
                f"agent {agent_name!r} resolves to no provider: set `provider` on its "
                f"block, or `default_provider` in {self.path}"
            )
        return self.providers[chosen]

    def live_agents(self) -> list[Agent]:
        return [a for a in self.agents.values() if a.live and a.sprite_id]


def _parse_provider(name: str, fields: dict) -> Provider:
    for key in ("base_url", "model"):
        if not fields.get(key):
            raise ValueError(f"provider {name!r}: `{key}` is required")
    auth = fields.get("auth", "connector")
    if auth not in AUTH_MODES:
        raise ValueError(f"provider {name!r}: unknown auth {auth!r} (want one of {AUTH_MODES})")
    secret_env = fields.get("secret_env", "")
    if (auth == "secret_env") != bool(secret_env):
        raise ValueError(
            f"provider {name!r}: `secret_env` is required by, and only by, auth = 'secret_env'"
        )
    return Provider(
        name=name,
        base_url=fields["base_url"].rstrip("/"),
        model=fields["model"],
        auth=auth,
        secret_env=secret_env,
        context_window=int(fields.get("context_window", 0)),
    )


def load_config(path: Path | str = "slop_salon.toml") -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    with p.open("rb") as f:
        data = tomllib.load(f)

    providers = {
        name: _parse_provider(name, fields) for name, fields in data.get("providers", {}).items()
    }
    default_provider = data.get("default_provider", "")
    if default_provider and default_provider not in providers:
        raise ValueError(f"default_provider {default_provider!r} has no [providers.*] block in {p}")

    salons = {}
    for name, fields in data.get("salons", {}).items():
        provider = fields.get("provider", "")
        if provider and provider not in providers:
            raise ValueError(f"salon {name!r}: provider {provider!r} has no [providers.*] block")
        salons[name] = Salon(name=name, label=fields.get("label", name), provider=provider)

    souls = {
        name: Soul(name=name, label=fields.get("label", name))
        for name, fields in data.get("souls", {}).items()
    }

    agents = {}
    for name, fields in data.get("agents", {}).items():
        if "siblings" in fields:
            raise ValueError(f"agent {name!r}: `siblings` is derived from `salon`; delete the list")
        provider = fields.get("provider", "")
        if provider and provider not in providers:
            raise ValueError(f"agent {name!r}: provider {provider!r} has no [providers.*] block")
        salon = fields.get("salon", "")
        if salon and salon not in salons:
            raise ValueError(f"agent {name!r}: salon {salon!r} has no [salons.*] block")
        soul = fields.get("soul", "")
        if soul and soul not in souls:
            raise ValueError(f"agent {name!r}: soul {soul!r} has no [souls.*] block")
        agents[name] = Agent(
            name=name,
            handle=fields["handle"],
            github_repo=fields["github_repo"],
            sprite_id=fields.get("sprite_id", ""),
            salon=salon,
            soul=soul,
            namesake=fields.get("namesake", ""),
            namesake_url=fields.get("namesake_url", ""),
            live=bool(fields.get("live", False)),
            provider=provider,
        )
    for agent in agents.values():
        if agent.salon:
            agent.siblings = [
                other.name
                for other in agents.values()
                if other.salon == agent.salon and other.name != agent.name
            ]
    return Config(
        path=p,
        agents=agents,
        providers=providers,
        salons=salons,
        souls=souls,
        default_provider=default_provider,
        claude_version=data.get("claude_version", ""),
    )


def save_sprite_id(config: Config, agent_name: str, sprite_id: str) -> None:
    """Set `sprite_id` inside the `[agents.<name>]` block, textually, so comments
    and layout survive. Replaces the value if present, else inserts it after the
    section header."""
    text = config.path.read_text()
    replace_pattern = re.compile(
        rf"(\[agents\.{re.escape(agent_name)}\][^\[]*sprite_id\s*=\s*)\"[^\"]*\"",
        re.DOTALL,
    )
    new_text, n = replace_pattern.subn(rf'\1"{sprite_id}"', text)
    if n != 1:
        insert_pattern = re.compile(rf"(\[agents\.{re.escape(agent_name)}\]\n)")
        new_text, n = insert_pattern.subn(rf'\1sprite_id = "{sprite_id}"\n', text)
        if n != 1:
            raise ValueError(f"could not find [agents.{agent_name}] section in {config.path}")
    config.path.write_text(new_text)
