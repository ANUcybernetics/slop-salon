"""Parse and represent slop_salon.toml configuration."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# The agent CLIs we know how to drive. `slop-tick` dispatches on this.
RUNNERS = ("claude", "codex")


@dataclass(frozen=True)
class Pricing:
    """Per-million-token rates for a metered provider.

    Only providers that actually bill per token carry one. A self-hosted
    endpoint or a subscription has no per-token price, and `slop usage` prints
    `--` for those rather than a number --- the previous behaviour, a notional
    Sonnet-equivalent applied to every provider alike, overstated a real
    DeepSeek wake by ~40x while looking exactly like a real figure.
    """

    input: float
    output: float
    cache_read: float = 0.0
    cache_write: float = 0.0


@dataclass
class Provider:
    """One intelligence provider --- where an agent's thinking comes from.

    A provider is two separable things: which agent CLI runs the tick
    (`runner`), and how that CLI reaches a model (`env` + `secret_env`, or an
    on-disk OAuth profile via `credentials_*`). Subscription auth is the case
    that makes the split worth having: it sets no env at all, because Claude
    Code resolves ANTHROPIC_API_KEY -> ANTHROPIC_AUTH_TOKEN -> the credentials
    file, and only falls through to the file when neither var is set.

    `secret_env` maps a *sprite-side* var name to the name of an admin-side env
    var holding the value (e.g. ANTHROPIC_API_KEY <- DEEPSEEK_API_TOKEN). The
    value never appears here: slop_salon.toml is tracked, and is inlined
    verbatim into the public site bundle by `site/src/lib/agents.ts`.
    """

    name: str
    runner: str = "claude"
    # Shared dotfiles dispatcher profile. Runner remains explicit because
    # sprite-side preparation (AGENTS.md rendering, hooks, usage parsing) needs
    # to know which CLI the profile launches without loading another registry.
    profile: str = ""
    # Literal, non-secret env for the sprite (base URL, model, timeouts).
    env: dict[str, str] = field(default_factory=dict)
    # sprite var name -> admin env var name holding its value.
    secret_env: dict[str, str] = field(default_factory=dict)
    # Pin the in-sprite Claude Code to this version. Empty means "leave it".
    claude_version: str = ""
    # Optional liveness probe for `slop wake-check`. Hosted APIs have none.
    health_url: str = ""
    # OAuth profile to drop into the sprite, and the admin-side path to read it
    # from. Both or neither.
    credentials_dest: str = ""
    credentials_source_env: str = ""
    # May more than one sprite hold this OAuth profile at once? False by
    # default: refresh tokens usually rotate on use, and a provider that
    # revokes the old one on rotation would have its sprites deauthenticate
    # each other. Set only where that has actually been tested.
    credentials_shareable: bool = False
    # Per-token rates, when the provider is metered. None means "not billed per
    # token" (self-hosted, or a subscription), not "free".
    pricing: Pricing | None = None

    @property
    def is_subscription(self) -> bool:
        return bool(self.credentials_dest)


@dataclass
class Salon:
    """One salon: the agents that know of each other, and the model they share.

    Season 2 runs several salons side by side on different models to see
    whether they individuate, so a salon is where the experiment's one variable
    lives: `provider` is the model, and everything else is held constant. An
    agent's siblings are *derived* from its salon --- every other agent in the
    same salon --- rather than listed by hand, so the sibling graph is closed
    by construction and adding an agent is one line, not N.
    """

    name: str
    # Human-readable name for the site ("GLM 5.3 Flash"). Defaults to the id.
    label: str = ""
    # Provider id every agent in the salon runs on, unless its own block
    # overrides it. "" defers to `default_provider`.
    provider: str = ""


@dataclass
class Agent:
    name: str
    handle: str
    github_repo: str
    sprite_id: str = ""
    # Filled by the loader from `salon`; never read from the file.
    siblings: list[str] = field(default_factory=list)
    namesake: str = ""
    namesake_url: str = ""
    live: bool = False
    # Salon id, or "" for an agent that knows nobody.
    salon: str = ""
    # Provider id override, or "" to take the salon's, then the registry default.
    provider: str = ""


@dataclass
class Config:
    path: Path
    agents: dict[str, Agent]
    providers: dict[str, Provider] = field(default_factory=dict)
    salons: dict[str, Salon] = field(default_factory=dict)
    default_provider: str = ""

    def members(self, salon_name: str) -> list[str]:
        """Agent names in salon `salon_name`, in registry order."""
        if salon_name not in self.salons:
            raise KeyError(f"unknown salon {salon_name!r}")
        return [a.name for a in self.agents.values() if a.salon == salon_name]

    def provider_for(self, agent_name: str) -> Provider:
        """The provider agent `agent_name` runs on.

        Precedence: the agent's own `provider`, then its salon's, then the
        registry `default_provider`. There is no fourth fallback: a config
        that resolves to nothing is a config error, and saying so beats
        quietly inventing an endpoint. The registry briefly carried a
        hardcoded vLLM provider for exactly that case, which meant the one
        situation it existed to rescue would have returned a tunnel that was
        switched off the same week.
        """
        if agent_name not in self.agents:
            raise KeyError(f"unknown agent {agent_name!r}")
        agent = self.agents[agent_name]
        salon_provider = self.salons[agent.salon].provider if agent.salon else ""
        chosen = agent.provider or salon_provider or self.default_provider
        if not chosen:
            raise ValueError(
                f"agent {agent_name!r} resolves to no provider: set `provider` on its "
                f"block, or `default_provider` in {self.path}"
            )
        return self.providers[chosen]


def _parse_provider(name: str, fields: dict) -> Provider:
    runner = fields.get("runner", "claude")
    if runner not in RUNNERS:
        raise ValueError(f"provider {name!r}: unknown runner {runner!r} (want one of {RUNNERS})")
    raw_pricing = fields.get("pricing")
    pricing = None
    if raw_pricing is not None:
        missing = {"input", "output"} - set(raw_pricing)
        if missing:
            raise ValueError(f"provider {name!r}: pricing needs {sorted(missing)}")
        pricing = Pricing(
            input=float(raw_pricing["input"]),
            output=float(raw_pricing["output"]),
            cache_read=float(raw_pricing.get("cache_read", 0.0)),
            cache_write=float(raw_pricing.get("cache_write", 0.0)),
        )
    credentials_dest = fields.get("credentials_dest", "")
    default_profile = (
        "codex-sub" if runner == "codex" else "claude-sub" if credentials_dest else "claude-api"
    )
    provider = Provider(
        name=name,
        runner=runner,
        profile=fields.get("profile", default_profile),
        env={k: str(v) for k, v in fields.get("env", {}).items()},
        secret_env=dict(fields.get("secret_env", {})),
        claude_version=fields.get("claude_version", ""),
        health_url=fields.get("health_url", ""),
        credentials_dest=credentials_dest,
        credentials_source_env=fields.get("credentials_source_env", ""),
        credentials_shareable=bool(fields.get("credentials_shareable", False)),
        pricing=pricing,
    )
    if bool(provider.credentials_dest) != bool(provider.credentials_source_env):
        raise ValueError(
            f"provider {name!r}: credentials_dest and credentials_source_env must be set together"
        )
    if provider.credentials_shareable and not provider.credentials_dest:
        raise ValueError(
            f"provider {name!r}: credentials_shareable is meaningless without credentials_dest"
        )
    return provider


def load_config(path: Path | str = "slop_salon.toml") -> Config:
    """Parse slop_salon.toml and return a Config."""
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
        agents[name] = Agent(
            name=name,
            handle=fields["handle"],
            github_repo=fields["github_repo"],
            sprite_id=fields.get("sprite_id", ""),
            namesake=fields.get("namesake", ""),
            namesake_url=fields.get("namesake_url", ""),
            live=bool(fields.get("live", False)),
            salon=salon,
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
        default_provider=default_provider,
    )


def _set_agent_field(config: Config, agent_name: str, key: str, value: str) -> None:
    """Set `key = "value"` inside the `[agents.<agent_name>]` block, in place.

    Rewrites the TOML textually rather than round-tripping it, so comments and
    layout survive. If the key is already there its value is replaced; if not,
    the line is inserted right after the section header.
    """
    text = config.path.read_text()
    replace_pattern = re.compile(
        rf"(\[agents\.{re.escape(agent_name)}\][^\[]*{re.escape(key)}\s*=\s*)\"[^\"]*\"",
        re.DOTALL,
    )
    new_text, n = replace_pattern.subn(rf'\1"{value}"', text)
    if n == 1:
        config.path.write_text(new_text)
        return

    insert_pattern = re.compile(rf"(\[agents\.{re.escape(agent_name)}\]\n)")
    new_text, n = insert_pattern.subn(rf'\1{key} = "{value}"\n', text)
    if n != 1:
        raise ValueError(f"could not find [agents.{agent_name}] section in {config.path}")
    config.path.write_text(new_text)


def save_sprite_id(config: Config, agent_name: str, sprite_id: str) -> None:
    """Update slop_salon.toml in place to record a freshly-provisioned sprite ID."""
    _set_agent_field(config, agent_name, "sprite_id", sprite_id)


def save_provider(config: Config, agent_name: str, provider: str) -> None:
    """Update slop_salon.toml in place to record an agent's provider."""
    _set_agent_field(config, agent_name, "provider", provider)
