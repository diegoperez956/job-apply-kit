"""Post-interview opt-ins. Credentials live only in the process environment."""

from __future__ import annotations

import os
import tempfile
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

LOCAL_CONFIG = Path("config/integrations.local.yaml")


class IntegrationError(ValueError):
    pass


class Integrations(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    jev_enabled: StrictBool = False
    # Zero is a closed budget gate, not unlimited spending.
    jev_daily_usd: Decimal = Field(default=Decimal(0), ge=0)
    jev_monthly_usd: Decimal = Field(default=Decimal(0), ge=0)
    simplify_enabled: StrictBool = False
    simplify_risk_accepted: StrictBool = False


def load_integrations(path: Path = LOCAL_CONFIG) -> Integrations:
    if not path.exists():
        return Integrations()
    try:
        return Integrations.model_validate(yaml.safe_load(path.read_text()))
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        # Never echo arbitrary configuration content (it may contain a pasted key).
        raise IntegrationError("invalid local integration config") from exc


def save_integrations(settings: Integrations, path: Path = LOCAL_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise IntegrationError("refusing a symlinked integration config")
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(yaml.safe_dump(settings.model_dump(mode="json")))
        os.replace(temporary, path)  # mkstemp creates a private, mode-0600 file.
    finally:
        Path(temporary).unlink(missing_ok=True)


def typesafe_key() -> str | None:
    return os.environ.get("TYPESAFE_API_KEY", "").strip() or None


def _ask(prompt: str) -> bool:
    while True:
        answer = input(prompt + " [y/N] ").strip().casefold()
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        print("Answer yes or no.")


def setup(args) -> int:
    from .profile import load_profile

    load_profile(args.profile)  # This flow comes AFTER the profile interview.
    print("TYPESAFE_API_KEY: " + ("present (value hidden)" if typesafe_key() else "absent"))
    print("Jev is optional. It sends job descriptions and confirmed skill names to TypeSafe.")
    print("Recommended default: keyword-only. No resume bullets or contact details are sent.")
    jev = args.jev == "yes" if args.jev is not None else _ask("Wire in Jev?")
    daily = args.daily_budget
    monthly = args.monthly_budget
    if jev and args.jev is None:
        daily = input("Daily local USD cap (0 blocks calls): ").strip() or "0"
        monthly = input("Monthly local USD cap (0 blocks calls): ").strip() or "0"
    if jev:
        print("Get a dedicated API key from https://typesafe.ai and export TYPESAFE_API_KEY.")
        print("Never paste the key into chat, profile YAML, git, or command-line arguments.")
        if not typesafe_key():
            print("No key yet: keyword fallback stays active until you export one.")
    print("Simplify is human-operated: install Copilot, sign in yourself, review every field.")
    simplify = (
        args.simplify == "yes" if args.simplify is not None else _ask("Use Simplify Copilot?")
    )
    accepted = False
    if simplify:
        print("Read https://simplify.jobs/terms and docs/simplify.md before proceeding.")
        print("Account blocking, rate limits and personal-data disclosure are possible.")
        accepted = args.accept_simplify_risk or (
            args.simplify is None and _ask("Read the terms and accept these account risks?")
        )
        if not accepted:
            print("Risk not accepted: Simplify handoff remains disabled.")
    try:
        settings = Integrations(
            jev_enabled=jev,
            jev_daily_usd=daily or "0",
            jev_monthly_usd=monthly or "0",
            simplify_enabled=simplify and accepted,
            simplify_risk_accepted=accepted,
        )
    except ValidationError as exc:
        raise IntegrationError("budgets must be finite, nonnegative USD amounts") from exc
    save_integrations(settings)
    print("Saved local opt-ins (no credentials). Keyword ranking always remains available.")
    return 0
