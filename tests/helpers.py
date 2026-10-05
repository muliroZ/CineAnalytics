"""Modelo falso roteirizado, compartilhado pelos testes."""

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel


def scripted(*steps: str):
    """Cada passo é um SQL (vira chamada de run_sql) ou um texto final ("FINAL: ...").

    Os passos se repetem por pergunta: o modelo volta ao início sempre que recebe
    uma mensagem nova do usuário. Retorna (modelo, lista de chamadas recebidas).
    """
    calls: list[list[ModelMessage]] = []
    state = {"step": 0, "seen_prompts": 0}

    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompts = sum(1 for m in messages for p in getattr(m, "parts", []) if p.part_kind == "user-prompt")
        if prompts != state["seen_prompts"]:
            state.update(step=0, seen_prompts=prompts)
        calls.append(list(messages))
        step = steps[min(state["step"], len(steps) - 1)]
        state["step"] += 1
        if step.startswith("FINAL:"):
            return ModelResponse(parts=[TextPart(step.removeprefix("FINAL:").strip())])
        return ModelResponse(parts=[ToolCallPart("run_sql", {"sql": step})])

    return FunctionModel(fn), calls