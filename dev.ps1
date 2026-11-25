<#
.SYNOPSIS
    Start the local dev stack in one console; Ctrl+C stops all of it.

.DESCRIPTION
    Brings up Postgres and Redis (docker compose), then runs the chosen
    services side by side with their output prefixed by name. Ctrl+C, or any
    one service exiting, stops every service and its child processes. The
    database and Redis containers are left running.

    Never touches staging or production: those deploy through CI and ArgoCD.

.PARAMETER Services
    Which services to run: backend, frontend, celery (the worker), beat
    (celery beat, the daily margin and telemetry jobs).
    Default: backend, frontend, celery.

.PARAMETER NoInfra
    Do not run "docker compose up -d postgres redis" first.

.PARAMETER Migrate
    Run "alembic upgrade head" before starting. The backend must start after
    migrating: in development it creates missing tables on startup, which a
    later migration would then trip over.

.PARAMETER BackendPort
    Port for uvicorn. Default 8000.

.PARAMETER FrontendPort
    Port for Vite. Default 5173. The frontend reaches the API through
    VITE_API_URL, so change that too if you move the backend.

.EXAMPLE
    .\dev.ps1

.EXAMPLE
    .\dev.ps1 -Services backend,celery,beat -Migrate
#>
param(
    [string[]]$Services = @('backend', 'frontend', 'celery'),
    [switch]$NoInfra,
    [switch]$Migrate,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'

# name -> how to start it. Vite runs through node directly, not npm.cmd, so
# stopping it never leaves cmd's "Terminate batch job (Y/N)?" prompt behind.
# Celery's prefork pool does not work on Windows; solo runs tasks in-process.
# Keep --reload on the backend: on Windows it is what makes uvicorn use a selector
# event loop, which psycopg's async mode needs (without it the API exits at startup).
$definitions = @{
    backend  = @{ Dir = $backend; Exe = 'poetry'; Color = 'Cyan'
                  Args = "run uvicorn app.main:app --reload --port $BackendPort" }
    frontend = @{ Dir = $frontend; Exe = 'node'; Color = 'Magenta'
                  Args = "node_modules/vite/bin/vite.js --port $FrontendPort --strictPort" }
    celery   = @{ Dir = $backend; Exe = 'poetry'; Color = 'Yellow'
                  Args = 'run celery -A app.tasks.celery_app worker --pool=solo --loglevel=info' }
    beat     = @{ Dir = $backend; Exe = 'poetry'; Color = 'Green'
                  Args = 'run celery -A app.tasks.celery_app beat --loglevel=info' }
}

# "powershell -File dev.ps1 -Services backend,beat" passes one string, not a list.
$Services = @($Services | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } |
    Where-Object { $_ } | Select-Object -Unique)
$unknown = @($Services | Where-Object { -not $definitions.ContainsKey($_) })
if ($unknown.Count -gt 0) {
    throw "Unknown service(s): $($unknown -join ', '). Choose from: backend, frontend, celery, beat."
}

function Write-Tagged([string]$Name, [string]$Line, [string]$Color) {
    Write-Host ("[{0}] " -f $Name.PadRight(8)) -ForegroundColor $Color -NoNewline
    Write-Host $Line
}

function Stop-Tree([System.Diagnostics.Process]$Process) {
    if (-not $Process.HasExited) {
        # /T takes the children too: uvicorn's reloader and its server, node's workers.
        & taskkill.exe /PID $Process.Id /T /F 2>&1 | Out-Null
    }
}

if (-not $NoInfra) {
    Write-Host 'Starting postgres and redis...'
    & docker compose -f (Join-Path $root 'docker-compose.yml') up -d postgres redis
    if ($LASTEXITCODE -ne 0) { throw 'docker compose failed; is Docker running?' }
}

if ($Migrate) {
    Write-Host 'Migrating the database...'
    Push-Location $backend
    try {
        & poetry run alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade failed' }
    } finally { Pop-Location }
}

if ($Services -contains 'frontend' -and -not (Test-Path (Join-Path $frontend 'node_modules/vite'))) {
    throw 'frontend/node_modules is missing; run "npm install" in frontend first.'
}

$running = @()
try {
    foreach ($name in $Services) {
        $def = $definitions[$name]
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = (Get-Command $def.Exe).Source
        $info.Arguments = $def.Args
        $info.WorkingDirectory = $def.Dir
        $info.UseShellExecute = $false
        $info.RedirectStandardOutput = $true
        $info.RedirectStandardError = $true
        $info.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $info.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        # An empty stdin: nothing here can type into a service.
        $info.RedirectStandardInput = $true
        # A console of its own: Ctrl+C here reaches only this script, which
        # then stops each service and its children in the finally block.
        $info.CreateNoWindow = $true
        $info.EnvironmentVariables['PYTHONUNBUFFERED'] = '1'

        $process = New-Object System.Diagnostics.Process
        $process.StartInfo = $info
        $tag = @{ Name = $name; Color = $def.Color }
        Register-ObjectEvent $process OutputDataReceived -MessageData $tag | Out-Null
        Register-ObjectEvent $process ErrorDataReceived -MessageData $tag | Out-Null
        [void]$process.Start()
        $process.StandardInput.Close()
        $process.BeginOutputReadLine()
        $process.BeginErrorReadLine()
        $running += @{ Name = $name; Process = $process }
        Write-Tagged $name "started (pid $($process.Id)): $($def.Exe) $($def.Args)" $def.Color
    }

    # Ctrl+C is read as a key rather than left to stop the pipeline: a stopping
    # pipeline cuts a finally block short at its first native command, which
    # would leave services running. Without a console (input redirected),
    # fall back to the finally block alone.
    $readKeys = $true
    try { [Console]::TreatControlCAsInput = $true } catch { $readKeys = $false }

    Write-Host "Running $($Services -join ', '). Press Ctrl+C to stop all." -ForegroundColor White
    $stop = $false
    while (-not $stop) {
        if ($readKeys) {
            try {
                while ([Console]::KeyAvailable) {
                    $key = [Console]::ReadKey($true)
                    if ($key.Key -eq 'C' -and ($key.Modifiers -band [ConsoleModifiers]::Control)) {
                        Write-Host 'Ctrl+C: stopping all services.' -ForegroundColor White
                        $stop = $true
                    }
                }
            } catch { $readKeys = $false }
            if ($stop) { break }
        }
        $event = Wait-Event -Timeout 1
        while ($event) {
            $line = $event.SourceEventArgs.Data
            if ($null -ne $line) {
                Write-Tagged $event.MessageData.Name $line $event.MessageData.Color
            }
            Remove-Event -EventIdentifier $event.EventIdentifier
            $event = Get-Event | Select-Object -First 1
        }
        $exited = $running | Where-Object { $_.Process.HasExited } | Select-Object -First 1
        if ($exited) {
            Write-Host "$($exited.Name) exited with code $($exited.Process.ExitCode); stopping the rest." -ForegroundColor Red
            break
        }
    }
} finally {
    # Runs on Ctrl+C, on a service exiting and on an error.
    try { [Console]::TreatControlCAsInput = $false } catch { }
    foreach ($entry in $running) {
        Stop-Tree $entry.Process
        Write-Tagged $entry.Name 'stopped' 'DarkGray'
    }
    if (-not $NoInfra) {
        Write-Host 'postgres and redis are still running (docker compose stop to stop them).' -ForegroundColor DarkGray
    }
    Get-EventSubscriber -ErrorAction SilentlyContinue | Unregister-Event -ErrorAction SilentlyContinue
    Get-Event -ErrorAction SilentlyContinue | Remove-Event -ErrorAction SilentlyContinue
}
