"""Ask for each API key (typing is hidden) and write it into .env. Press Enter to keep the current value."""
import getpass

from .common import ROOT

KEYS = ["GEMINI_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "KAGGLE_USERNAME", "KAGGLE_API_TOKEN"]


def main() -> None:
    env = ROOT / ".env"
    if not env.exists():
        env.write_text((ROOT / ".env.example").read_text())
    lines = env.read_text().splitlines()

    def current(key):
        return next((l.split("=", 1)[1].strip() for l in lines if l.startswith(key + "=")), "")

    for key in KEYS:
        value = getpass.getpass(f"{key} ({'set' if current(key) else 'empty'}; paste + Enter, or Enter to keep): ").strip()
        if value:
            lines = [f"{key}={value}" if l.startswith(key + "=") else l for l in lines]
            if not any(l.startswith(key + "=") for l in lines):
                lines.append(f"{key}={value}")
    env.write_text("\n".join(lines) + "\n")
    print("saved .env: " + ", ".join(f"{k} {'set' if current(k) else 'EMPTY'}" for k in KEYS))


if __name__ == "__main__":
    main()
