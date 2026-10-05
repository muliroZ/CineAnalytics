<#
.SYNOPSIS
    Instala o comando `cineanalytics` globalmente (Windows).

.DESCRIPTION
    1. Instala o uv, se necessário (com confirmação).
    2. Instala o pacote com `uv tool install`, num ambiente isolado.
    3. Coloca a pasta de executáveis do uv no PATH do usuário.
    4. Cria o .env global com a chave, os modelos e caminhos absolutos.
    5. Confere se o comando funciona fora da pasta do projeto.

    Execute a partir da pasta do projeto:
        powershell -ExecutionPolicy Bypass -File .\install.ps1

.PARAMETER DbPath
    Caminho do cinerocket.db. Padrão: data\cinerocket.db dentro do projeto.

.PARAMETER Yes
    Não faz perguntas (usa os padrões e confirma tudo).

.PARAMETER Uninstall
    Remove o comando. A configuração é mantida, a menos que -Purge seja usado.

.PARAMETER Purge
    Junto com -Uninstall, apaga também a configuração, o cache, o histórico e os relatórios.

.EXAMPLE
    .\install.ps1
.EXAMPLE
    .\install.ps1 -DbPath C:\dados\cinerocket.db
.EXAMPLE
    .\install.ps1 -Uninstall -Purge
#>
[CmdletBinding()]
param(
    [string]$DbPath,
    [Alias("y")][switch]$Yes,
    [switch]$Uninstall,
    [switch]$Purge
)

$ErrorActionPreference = "Stop"
$Package = "cineanalytics"
$RepoDir = $PSScriptRoot
$OnWindows = $env:OS -eq "Windows_NT"

if (-not $env:APPDATA -or -not $env:LOCALAPPDATA) {
    Write-Host "Erro: as variáveis APPDATA e LOCALAPPDATA não estão definidas. Este script é para Windows; no Linux e no macOS use install.sh." -ForegroundColor Red
    exit 1
}
$ConfigDir = if ($env:CINEANALYTICS_CONFIG_DIR) { $env:CINEANALYTICS_CONFIG_DIR } else { Join-Path $env:APPDATA "cineanalytics" }
$DataDir = Join-Path $env:LOCALAPPDATA "cineanalytics"
$EnvFile = Join-Path $ConfigDir ".env"

# ------------------------------------------------------------------ saída
function Write-Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Info([string]$Text) { Write-Host "    $Text" }
function Write-Ok([string]$Text) { Write-Host "    + " -ForegroundColor Green -NoNewline; Write-Host $Text }
function Write-Warn([string]$Text) { Write-Host "    ! " -ForegroundColor Yellow -NoNewline; Write-Host $Text }
function Stop-Install([string]$Text) {
    Write-Host ""
    Write-Host "Erro: $Text" -ForegroundColor Red
    exit 1
}

function Confirm-Action([string]$Question, [bool]$Default = $true) {
    if ($Yes) { return $true }  # -Yes: as opções passadas já expressam a decisão
    $hint = if ($Default) { "[S/n]" } else { "[s/N]" }
    $answer = Read-Host "    $Question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer -match '^[sSyY]'
}

# Executa o uv sem que mensagens no stderr virem exceção (comportamento do PowerShell 5.1).
function Invoke-Uv([string[]]$Arguments) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & uv @Arguments 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    return [pscustomobject]@{ Code = $code; Output = ($output -join "`n") }
}

function Test-Uv { return [bool](Get-Command uv -ErrorAction SilentlyContinue) }

function Get-EnvValue([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return "" }
    $match = Select-String -Path $Path -Pattern "^$Key=(.*)$" | Select-Object -Last 1
    if ($match) { return $match.Matches[0].Groups[1].Value.Trim() }
    return ""
}

function Write-Utf8File([string]$Path, [string]$Content) {
    # UTF-8 sem BOM: o BOM atrapalharia a leitura da primeira variável do .env.
    [IO.File]::WriteAllText($Path, $Content, [Text.UTF8Encoding]::new($false))
}

function Set-EnvValue([string]$Path, [string]$Key, [string]$Value) {
    $lines = [Collections.Generic.List[string]]::new()
    $found = $false
    foreach ($line in [IO.File]::ReadAllLines($Path)) {
        if ($line.StartsWith("$Key=")) { $lines.Add("$Key=$Value"); $found = $true }
        else { $lines.Add($line) }
    }
    if (-not $found) { $lines.Add("$Key=$Value") }
    Write-Utf8File $Path (($lines -join "`n") + "`n")
}

# Barras normais funcionam no Windows e evitam problemas de escape no .env.
function ConvertTo-EnvPath([string]$Path) { return $Path -replace '\\', '/' }

# ---------------------------------------------------------------- validação
if ($Purge -and -not $Uninstall) { Stop-Install "-Purge só pode ser usado junto com -Uninstall." }

# -------------------------------------------------------------- desinstalar
if ($Uninstall) {
    Write-Step "Removendo o CineAnalytics"
    if ((Test-Uv) -and ((Invoke-Uv @("tool", "list")).Output -match "(?m)^$Package ")) {
        $null = Invoke-Uv @("tool", "uninstall", $Package)
        Write-Ok "Comando cineanalytics removido"
    } else {
        Write-Info "O comando não estava instalado."
    }
    if ($Purge) {
        Write-Warn "Isto apaga a configuração (com a sua chave), o cache, o histórico e os relatórios:"
        Write-Info $ConfigDir
        Write-Info $DataDir
        if (Confirm-Action "Confirmar?" $false) {
            foreach ($dir in @($ConfigDir, $DataDir)) {
                if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }
            }
            Write-Ok "Configuração e dados removidos"
        }
    } else {
        Write-Info "Configuração mantida em $EnvFile (use -Purge para apagar)."
    }
    exit 0
}

# ------------------------------------------------------------------ instalar
Write-Host "CineAnalytics: instalação do comando global"
if (-not (Test-Path (Join-Path $RepoDir "pyproject.toml"))) {
    Stop-Install "Rode o script a partir da pasta do projeto (pyproject.toml não encontrado)."
}

Write-Step "1/5  Verificando o uv"
if (Test-Uv) {
    Write-Ok "uv $(((Invoke-Uv @('--version')).Output -split ' ')[1]) encontrado"
} else {
    Write-Warn "O uv não está instalado. Ele gerencia o Python e as dependências do CineAnalytics."
    if (-not (Confirm-Action "Instalar o uv agora (https://astral.sh/uv)?")) {
        Stop-Install "O uv é necessário. Veja https://docs.astral.sh/uv/"
    }
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    # O instalador do uv põe o executável em %USERPROFILE%\.local\bin; disponibiliza nesta sessão.
    $env:Path = (Join-Path $env:USERPROFILE ".local\bin") + [IO.Path]::PathSeparator + $env:Path
    if (-not (Test-Uv)) { Stop-Install "O uv foi instalado, mas não está no PATH. Abra um novo terminal e rode o script de novo." }
    Write-Ok "uv instalado"
}

Write-Step "2/5  Instalando o pacote"
Write-Info "Origem: $RepoDir"
Write-Info "O uv baixa o Python 3.11+ automaticamente, se necessário."
$result = Invoke-Uv @("tool", "install", "--force", "--reinstall", $RepoDir)
if ($result.Code -ne 0) {
    Write-Host $result.Output
    Stop-Install "Falha ao instalar o pacote (mensagens do uv acima)."
}
$BinDir = (Invoke-Uv @("tool", "dir", "--bin")).Output.Trim()
$ExeName = if ($OnWindows) { "cineanalytics.exe" } else { "cineanalytics" }
$Exe = Join-Path $BinDir $ExeName
Write-Ok "Instalado em $Exe"

Write-Step "3/5  Configurando o PATH"
$normalize = { param($p) $p.TrimEnd('\', '/').ToLowerInvariant() }
$inPath = $env:Path -split [IO.Path]::PathSeparator | Where-Object { $_ -and ((& $normalize $_) -eq (& $normalize $BinDir)) }
if ($inPath) {
    Write-Ok "$BinDir já está no PATH"
    $PathChanged = $false
} else {
    $null = Invoke-Uv @("tool", "update-shell")
    $env:Path = $BinDir + [IO.Path]::PathSeparator + $env:Path
    Write-Ok "$BinDir adicionado ao PATH do usuário"
    $PathChanged = $true
}

Write-Step "4/5  Configuração global"
New-Item -ItemType Directory -Force -Path $ConfigDir, $DataDir | Out-Null

# Caminho absoluto do banco: -DbPath, valor já configurado ou data\ do projeto.
if ($DbPath) {
    $full = if ([IO.Path]::IsPathRooted($DbPath)) { $DbPath } else { Join-Path (Get-Location).Path $DbPath }
    $DbFile = ConvertTo-EnvPath ([IO.Path]::GetFullPath($full))
} elseif (Get-EnvValue $EnvFile "CINEANALYTICS_DB_PATH") {
    $DbFile = Get-EnvValue $EnvFile "CINEANALYTICS_DB_PATH"
} else {
    $DbFile = ConvertTo-EnvPath (Join-Path $RepoDir "data\cinerocket.db")
}

if (Test-Path $EnvFile) {
    Write-Ok "Mantendo a configuração existente em $EnvFile"
    Set-EnvValue $EnvFile "CINEANALYTICS_DB_PATH" $DbFile
} else {
    # Reaproveita a chave e os modelos de um .env do projeto, se houver.
    $RepoEnv = Join-Path $RepoDir ".env"
    $Key = Get-EnvValue $RepoEnv "OPENROUTER_API_KEY"
    $Models = Get-EnvValue $RepoEnv "CINEANALYTICS_MODELS"
    if ($Key -or $Models) { Write-Ok "Chave e modelos copiados do .env do projeto" }

    if (-not $Key -and -not $Yes) {
        Write-Info "Chave do OpenRouter (https://openrouter.ai/settings/keys). Deixe vazio para preencher depois."
        $secure = Read-Host "    OPENROUTER_API_KEY" -AsSecureString
        $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        try { $Key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    }
    if (-not $Models -and -not $Yes) {
        Write-Info "Modelos gratuitos com tool calling, separados por vírgula, em ordem de preferência."
        Write-Info "Lista: https://openrouter.ai/models?max_price=0&supported_parameters=tools"
        $Models = Read-Host "    CINEANALYTICS_MODELS"
    }

    $StateDir = ConvertTo-EnvPath (Join-Path $DataDir "state")
    $ReportsDir = ConvertTo-EnvPath (Join-Path $DataDir "reports")
    $now = Get-Date -Format "dd/MM/yyyy HH:mm"
    $content = @"
# Configuração global do CineAnalytics, criada por install.ps1 em $now.
# Vale em qualquer pasta. Um .env na pasta atual tem prioridade sobre este arquivo.
# Para ver a configuração em uso: cineanalytics config

OPENROUTER_API_KEY=$Key
CINEANALYTICS_MODELS=$Models

CINEANALYTICS_DB_PATH=$DbFile
CINEANALYTICS_STATE_DIR=$StateDir
CINEANALYTICS_REPORTS_DIR=$ReportsDir

# Opcionais (valores padrão)
# CINEANALYTICS_MAX_ROWS=50
# CINEANALYTICS_QUERY_TIMEOUT_S=10
# CINEANALYTICS_REQUEST_LIMIT=6
# CINEANALYTICS_HISTORY_TURNS=5
# CINEANALYTICS_CACHE_ENABLED=true
"@
    Write-Utf8File $EnvFile (($content -replace "`r`n", "`n") + "`n")
    Write-Ok "Criado $EnvFile"
    if (-not $Key) { Write-Warn "Chave não definida: edite o arquivo antes de fazer perguntas." }
    if (-not $Models) { Write-Warn "Modelos não definidos: edite o arquivo antes de fazer perguntas." }
}

if (Test-Path $DbFile) {
    Write-Ok "Banco: $DbFile"
} else {
    Write-Warn "Banco não encontrado em $DbFile"
    Write-Info "Copie o cinerocket.db para lá, ou rode de novo com -DbPath C:\caminho\para\cinerocket.db"
}

Write-Step "5/5  Verificando"
# Executa o comando a partir da pasta do usuário, fora do projeto.
function Test-Command([string[]]$Arguments) {
    Push-Location $HOME
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Exe @Arguments *> $null; return $LASTEXITCODE -eq 0 }
    finally { $ErrorActionPreference = $previous; Pop-Location }
}
if (Test-Command @("--help")) {
    Write-Ok "O comando responde fora da pasta do projeto"
} else {
    Stop-Install "O comando foi instalado, mas não executou. Rode '$Exe --help' para ver o erro."
}
if (Test-Path $DbFile) {
    if (Test-Command @("schema")) { Write-Ok "O banco abre corretamente" }
    else { Write-Warn "O banco não abriu. Rode 'cineanalytics schema' para ver o erro." }
}

Write-Host ""
Write-Host "Pronto! " -ForegroundColor Green -NoNewline
Write-Host "Experimente em qualquer pasta:"
Write-Host ""
Write-Host "    cineanalytics config"
Write-Host '    cineanalytics ask "Quais são os 5 filmes mais populares?"'
Write-Host ""
if ($PathChanged) {
    Write-Host "Abra um novo terminal para o comando ficar disponível." -ForegroundColor Yellow
}
Write-Host "Para atualizar depois de um git pull, rode este script de novo." -ForegroundColor DarkGray