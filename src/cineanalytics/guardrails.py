"""Validação do SQL gerado pelo LLM antes da execução.

Esta é a primeira camada de defesa e a que gera mensagens úteis para o modelo
corrigir a própria consulta. As outras duas ficam em db.py: a conexão é aberta
em modo somente leitura e um authorizer do SQLite bloqueia qualquer operação
que não seja leitura.
"""

from __future__ import annotations

from collections.abc import Collection

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class SQLValidationError(ValueError):
    """SQL rejeitado. A mensagem é escrita para ser devolvida ao modelo."""


def _types(*names: str) -> tuple[type, ...]:
    # getattr protege contra diferenças de nomes entre versões do sqlglot.
    return tuple(t for n in names if isinstance(t := getattr(exp, n, None), type))


_QUERY_ROOTS = _types("Select", "Union", "Intersect", "Except", "SetOperation")
_FORBIDDEN = _types(
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "TruncateTable",
    "Command", "Pragma", "Attach", "Detach", "Transaction", "Commit", "Rollback",
)


def validate_select(sql: str, allowed_tables: Collection[str]) -> str:
    """Garante que `sql` é uma única consulta de leitura sobre tabelas permitidas.

    Retorna o SQL limpo (sem espaços e `;` finais) ou levanta SQLValidationError.
    """
    cleaned = sql.strip().rstrip(";").strip()
    if not cleaned:
        raise SQLValidationError("A consulta está vazia.")

    try:
        statements = [s for s in sqlglot.parse(cleaned, read="sqlite") if s is not None]
    except ParseError as e:
        detail = e.errors[0].get("description", str(e)) if e.errors else str(e)
        raise SQLValidationError(f"Erro de sintaxe no SQL: {detail}") from e

    if len(statements) != 1:
        raise SQLValidationError("Envie exatamente uma consulta por vez, sem ';' no meio.")

    tree = statements[0]
    if not isinstance(tree, _QUERY_ROOTS) or tree.find(*_FORBIDDEN) is not None:
        raise SQLValidationError("Apenas consultas de leitura (SELECT / WITH ... SELECT) são permitidas.")

    allowed = {t.lower() for t in allowed_tables}
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}

    for table in tree.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            raise SQLValidationError("Funções de tabela não são permitidas no FROM.")
        name = table.name.lower()
        if table.db and table.db.lower() != "temp":
            raise SQLValidationError(f"Não use prefixo de schema em '{table.db}.{table.name}'.")
        if name in cte_names:
            continue
        if name not in allowed:
            raise SQLValidationError(
                f"Tabela '{table.name}' não disponível. Use apenas: {', '.join(sorted(allowed))}."
            )

    return cleaned