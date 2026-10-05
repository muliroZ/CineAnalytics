#!/usr/bin/env bash
# Instala o comando `cineanalytics` globalmente (Linux e macOS).
#
# Uso:
#   ./install.sh                     instala ou atualiza
#   ./install.sh --db /caminho.db    informa onde está o cinerocket.db
#   ./install.sh --yes               não faz perguntas (usa os padrões)
#   ./install.sh --uninstall         remove o comando (mantém a configuração)
#   ./install.sh --uninstall --purge remove o comando, a configuração, o cache e o histórico
#
# O que o script faz:
#   1. instala o uv, se necessário (com confirmação);
#   2. instala o pacote com `uv tool install`, num ambiente isolado;
#   3. coloca a pasta de executáveis do uv no PATH;
#   4. cria o .env global com a chave, os modelos e caminhos absolutos;
#   5. confere se o comando funciona fora da pasta do projeto.

set -euo pipefail

PACKAGE="cineanalytics"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${CINEANALYTICS_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/cineanalytics}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/cineanalytics"
ENV_FILE="$CONFIG_DIR/.env"

DB_PATH=""
ASSUME_YES=0
UNINSTALL=0
PURGE=0

# ------------------------------------------------------------------ saída
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi
step() { printf '\n%s==>%s %s%s%s\n' "$BOLD" "$RESET" "$BOLD" "$1" "$RESET"; }
info() { printf '    %s\n' "$1"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
die()  { printf '\n%sErro:%s %s\n' "$RED" "$RESET" "$1" >&2; exit 1; }

confirm() {  # confirm "pergunta" [padrão s|n]
  local default="${2:-s}" answer
  if [ "$ASSUME_YES" = 1 ]; then return 0; fi  # --yes: as opções passadas já expressam a decisão
  if [ "$default" = s ]; then read -r -p "    $1 [S/n] " answer || true; answer="${answer:-s}"
  else read -r -p "    $1 [s/N] " answer || true; answer="${answer:-n}"; fi
  [[ "$answer" =~ ^[sSyY] ]]
}

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

# --------------------------------------------------------------- argumentos
while [ $# -gt 0 ]; do
  case "$1" in
    --db)        [ $# -ge 2 ] || die "--db precisa de um caminho."; DB_PATH="$2"; shift 2 ;;
    --db=*)      DB_PATH="${1#*=}"; shift ;;
    -y|--yes)    ASSUME_YES=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    --purge)     PURGE=1; shift ;;
    -h|--help)   usage ;;
    *)           die "Opção desconhecida: $1 (use --help)." ;;
  esac
done
if [ "$PURGE" = 1 ] && [ "$UNINSTALL" = 0 ]; then die "--purge só pode ser usado junto com --uninstall."; fi

# ---------------------------------------------------------------------- uv
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version | awk '{print $2}') encontrado"
    return
  fi
  warn "O uv não está instalado. Ele gerencia o Python e as dependências do CineAnalytics."
  confirm "Instalar o uv agora (https://astral.sh/uv)?" s || die "O uv é necessário. Veja https://docs.astral.sh/uv/"
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    die "É preciso curl ou wget para instalar o uv."
  fi
  # O instalador do uv põe o executável em ~/.local/bin; disponibiliza nesta sessão.
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "O uv foi instalado, mas não está no PATH. Abra um novo terminal e rode o script de novo."
  ok "uv instalado"
}

# -------------------------------------------------------------- desinstalar
if [ "$UNINSTALL" = 1 ]; then
  step "Removendo o CineAnalytics"
  if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q "^$PACKAGE "; then
    uv tool uninstall "$PACKAGE" >/dev/null 2>&1
    ok "Comando cineanalytics removido"
  else
    info "O comando não estava instalado."
  fi
  if [ "$PURGE" = 1 ]; then
    warn "Isto apaga a configuração (com a sua chave), o cache, o histórico e os relatórios:"
    info "$CONFIG_DIR"
    info "$DATA_DIR"
    if confirm "Confirmar?" n; then
      rm -rf "$CONFIG_DIR" "$DATA_DIR"
      ok "Configuração e dados removidos"
    fi
  else
    info "Configuração mantida em $ENV_FILE (use --purge para apagar)."
  fi
  exit 0
fi

# ------------------------------------------------------------------ instalar
printf '%sCineAnalytics%s: instalação do comando global\n' "$BOLD" "$RESET"
[ -f "$REPO_DIR/pyproject.toml" ] || die "Rode o script a partir da pasta do projeto (pyproject.toml não encontrado)."

step "1/5  Verificando o uv"
ensure_uv

step "2/5  Instalando o pacote"
info "Origem: $REPO_DIR"
info "${DIM}O uv baixa o Python 3.11+ automaticamente, se necessário.${RESET}"
LOG="$(mktemp)"
if uv tool install --force --reinstall "$REPO_DIR" >"$LOG" 2>&1; then
  rm -f "$LOG"
else
  cat "$LOG" >&2; rm -f "$LOG"
  die "Falha ao instalar o pacote (mensagens do uv acima)."
fi
BIN_DIR="$(uv tool dir --bin)"
ok "Instalado em $BIN_DIR/cineanalytics"

step "3/5  Configurando o PATH"
case ":$PATH:" in
  *":$BIN_DIR:"*)
    ok "$BIN_DIR já está no PATH"
    PATH_CHANGED=0 ;;
  *)
    uv tool update-shell >/dev/null 2>&1 || true
    export PATH="$BIN_DIR:$PATH"
    ok "$BIN_DIR adicionado ao PATH no arquivo de inicialização do shell"
    PATH_CHANGED=1 ;;
esac

step "4/5  Configuração global"
mkdir -p "$CONFIG_DIR" "$DATA_DIR"

# Caminho absoluto do banco: --db, valor já configurado ou data/ do projeto.
existing_value() {
  if [ -f "$ENV_FILE" ]; then grep -E "^$1=" "$ENV_FILE" | tail -n1 | cut -d= -f2- || true; fi
}
if [ -n "$DB_PATH" ]; then
  case "$DB_PATH" in /*) ;; ~*) DB_PATH="${DB_PATH/#\~/$HOME}" ;; *) DB_PATH="$PWD/$DB_PATH" ;; esac
elif [ -n "$(existing_value CINEANALYTICS_DB_PATH)" ]; then
  DB_PATH="$(existing_value CINEANALYTICS_DB_PATH)"
else
  DB_PATH="$REPO_DIR/data/cinerocket.db"
fi

set_env_value() {  # set_env_value CHAVE valor: substitui a linha ou acrescenta no fim
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  if grep -qE "^$key=" "$ENV_FILE"; then
    awk -v k="$key" -v v="$value" 'index($0, k"=") == 1 { print k"="v; next } { print }' "$ENV_FILE" > "$tmp"
  else
    cat "$ENV_FILE" > "$tmp"; printf '%s=%s\n' "$key" "$value" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
}

if [ -f "$ENV_FILE" ]; then
  ok "Mantendo a configuração existente em $ENV_FILE"
  set_env_value CINEANALYTICS_DB_PATH "$DB_PATH"
else
  # Reaproveita a chave e os modelos de um .env do projeto, se houver.
  KEY=""; MODELS=""
  if [ -f "$REPO_DIR/.env" ]; then
    KEY="$(grep -E '^OPENROUTER_API_KEY=' "$REPO_DIR/.env" | tail -n1 | cut -d= -f2- || true)"
    MODELS="$(grep -E '^CINEANALYTICS_MODELS=' "$REPO_DIR/.env" | tail -n1 | cut -d= -f2- || true)"
    if [ -n "$KEY$MODELS" ]; then ok "Chave e modelos copiados do .env do projeto"; fi
  fi
  if [ -z "$KEY" ] && [ "$ASSUME_YES" = 0 ]; then
    info "Chave do OpenRouter (https://openrouter.ai/settings/keys). Deixe vazio para preencher depois."
    read -r -s -p "    OPENROUTER_API_KEY: " KEY || true; echo
  fi
  if [ -z "$MODELS" ] && [ "$ASSUME_YES" = 0 ]; then
    info "Modelos gratuitos com tool calling, separados por vírgula, em ordem de preferência."
    info "${DIM}Lista: https://openrouter.ai/models?max_price=0&supported_parameters=tools${RESET}"
    read -r -p "    CINEANALYTICS_MODELS: " MODELS || true
  fi

  umask 077  # o arquivo guarda a chave: só o dono pode ler
  cat > "$ENV_FILE" <<EOF
# Configuração global do CineAnalytics, criada por install.sh em $(date '+%d/%m/%Y %H:%M').
# Vale em qualquer pasta. Um .env na pasta atual tem prioridade sobre este arquivo.
# Para ver a configuração em uso: cineanalytics config

OPENROUTER_API_KEY=$KEY
CINEANALYTICS_MODELS=$MODELS

CINEANALYTICS_DB_PATH=$DB_PATH
CINEANALYTICS_STATE_DIR=$DATA_DIR/state
CINEANALYTICS_REPORTS_DIR=$DATA_DIR/reports

# Opcionais (valores padrão)
# CINEANALYTICS_MAX_ROWS=50
# CINEANALYTICS_QUERY_TIMEOUT_S=10
# CINEANALYTICS_REQUEST_LIMIT=6
# CINEANALYTICS_HISTORY_TURNS=5
# CINEANALYTICS_CACHE_ENABLED=true
EOF
  chmod 600 "$ENV_FILE"
  ok "Criado $ENV_FILE"
  if [ -z "$KEY" ]; then warn "Chave não definida: edite o arquivo antes de fazer perguntas."; fi
  if [ -z "$MODELS" ]; then warn "Modelos não definidos: edite o arquivo antes de fazer perguntas."; fi
fi

if [ -f "$DB_PATH" ]; then
  ok "Banco: $DB_PATH"
else
  warn "Banco não encontrado em $DB_PATH"
  info "Copie o cinerocket.db para lá, ou rode de novo com --db /caminho/para/cinerocket.db"
fi

step "5/5  Verificando"
if (cd "$HOME" && "$BIN_DIR/cineanalytics" --help >/dev/null 2>&1); then
  ok "O comando responde fora da pasta do projeto"
else
  die "O comando foi instalado, mas não executou. Rode '$BIN_DIR/cineanalytics --help' para ver o erro."
fi
if [ -f "$DB_PATH" ]; then
  if (cd "$HOME" && "$BIN_DIR/cineanalytics" schema >/dev/null 2>&1); then
    ok "O banco abre corretamente"
  else
    warn "O banco não abriu. Rode 'cineanalytics schema' para ver o erro."
  fi
fi

printf '\n%sPronto!%s Experimente em qualquer pasta:\n\n' "$GREEN$BOLD" "$RESET"
printf '    cineanalytics config\n'
printf '    cineanalytics ask "Quais são os 5 filmes mais populares?"\n\n'
if [ "$PATH_CHANGED" = 1 ]; then
  printf '%sAbra um novo terminal%s (ou rode: export PATH="%s:$PATH") para o comando ficar disponível.\n' \
    "$YELLOW" "$RESET" "$BIN_DIR"
fi
printf '%sPara atualizar depois de um git pull, rode este script de novo.%s\n' "$DIM" "$RESET"