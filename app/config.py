from dataclasses import dataclass
import os
from pathlib import Path


class DotEnvLoader:
    """Minimal .env loader so local secrets can stay out of source control."""

    def __init__(self, env_path: Path) -> None:
        self.env_path = env_path

    def load(self) -> None:
        if not self.env_path.exists():
            return

        for raw_line in self.env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    database_url: str
    youtube_api_key: str
    templates_dir: Path
    env_file: Path

    @classmethod
    def from_env(cls) -> "Settings":
        base_dir = Path(__file__).resolve().parent.parent
        env_file = base_dir / ".env"
        DotEnvLoader(env_file).load()

        return cls(
            base_dir=base_dir,
            database_url=os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/techdb"),
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            templates_dir=base_dir / "templates",
            env_file=env_file,
        )