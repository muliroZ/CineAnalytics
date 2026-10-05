"""Persistência local: cache de respostas e log das perguntas feitas.

Tudo fica em arquivos dentro de CINEDATA_STATE_DIR (padrão: .cinedata/).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pydantic import ValidationError

from .models import AgentRun


class ResponseCache:
    """Cache de respostas em arquivos JSON, um por pergunta.

    A chave combina a pergunta normalizada, o modelo e um hash do prompt.
    Mudar o glossário ou as views invalida o cache automaticamente.
    Os dados da camada Gold são estáticos, então não há expiração.
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    @staticmethod
    def normalize(question: str) -> str:
        text = " ".join(question.casefold().split())
        return re.sub(r"[\s?!.]+$", "", text)

    def key(self, question: str, *, model: str, prompt: str) -> str:
        payload = json.dumps(
            {
                "q": self.normalize(question),
                "model": model,
                "prompt": hashlib.sha256(prompt.encode()).hexdigest(),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:32]

    def get(self, key: str) -> AgentRun | None:
        path = self.directory / f"{key}.json"
        if not path.is_file():
            return None
        try:
            return AgentRun.model_validate_json(path.read_text(encoding="utf-8"))
        except (ValidationError, ValueError):
            return None  # arquivo corrompido ou de versão antiga: trata como miss

    def set(self, key: str, run: AgentRun) -> None:
        if not run.ok:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.directory / f"{key}.tmp"
        tmp.write_text(run.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.directory / f"{key}.json")

    def entries(self) -> list[Path]:
        return sorted(self.directory.glob("*.json")) if self.directory.is_dir() else []

    def clear(self) -> int:
        files = self.entries()
        for f in files:
            f.unlink()
        return len(files)


class RunLog:
    """Histórico de perguntas em JSON Lines, lido depois pelo relatório."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, run: AgentRun) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(run.model_dump_json() + "\n")

    def load(self) -> list[AgentRun]:
        if not self.path.is_file():
            return []
        runs = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                runs.append(AgentRun.model_validate_json(line))
            except (ValidationError, ValueError):
                continue
        return runs