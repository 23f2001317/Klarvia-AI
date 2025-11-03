$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "Starting Voice Bot development environment from: $root"

$env:PYTHONUNBUFFERED = "1"
if (-not $env:ENV) { $env:ENV = "development" }

# Load environment variables from .env if present (simple KEY=VALUE parser)
$envFile = Join-Path $root ".env"
if (Test-Path $envFile) {
	try {
		Get-Content $envFile | ForEach-Object {
			if ($_ -match '^[ \t]*#') { return }
			if ($_ -notmatch '=') { return }
			$parts = $_ -split '=', 2
			if ($parts.Length -eq 2) {
				$key = $parts[0].Trim()
				$val = $parts[1].Trim().Trim('"')
				if ($key) { Set-Item -Path Env:$key -Value $val -ErrorAction SilentlyContinue }
			}
		}
		Write-Host ".env loaded into environment" -ForegroundColor DarkGray
	} catch {
		Write-Host "Warning: failed to load .env" -ForegroundColor Yellow
	}
}

# If AssemblyAI key is not set, enable developer fake STT so streaming UI can be tested
if (-not $env:ASSEMBLYAI_API_KEY -and -not $env:FAKE_STT) {
	$env:FAKE_STT = "1"
	Write-Host "FAKE_STT=1 (AssemblyAI key not found). Using dev fake STT for partials." -ForegroundColor Yellow
}
$venvPython = Join-Path -Path $root -ChildPath "voicebot\.venv\Scripts\python.exe"
if (Test-Path $venvPython) {
	Write-Host "Using venv python at: $venvPython" -ForegroundColor Green
	& $venvPython -c "import importlib,sys; sys.exit(0 if importlib.util.find_spec('uvicorn') else 1)"
	if ($LASTEXITCODE -eq 0) {
		Start-Process -FilePath $venvPython -ArgumentList @('-m','uvicorn','ai.main:app','--host','127.0.0.1','--port','8001','--reload') -WorkingDirectory $root -WindowStyle Normal | Out-Null
	Write-Host "AI service start command launched (uvicorn ai.main:app on http://127.0.0.1:8001)"
	} else {
	Write-Host "uvicorn not found in venv. Installing into venv..." -ForegroundColor Yellow
		& $venvPython -m pip install uvicorn
	Start-Process -FilePath $venvPython -ArgumentList @('-m','uvicorn','ai.main:app','--host','127.0.0.1','--port','8001','--reload') -WorkingDirectory $root -WindowStyle Normal | Out-Null
	Write-Host "🤖 AI service start command launched (uvicorn ai.main:app on http://127.0.0.1:8001)"
	}
} else {
	# Try using the Python launcher 'py' first (Windows), fall back to 'python'
	$pyCmd = Get-Command py -ErrorAction SilentlyContinue
	if ($pyCmd) {
		try {
			Start-Process -FilePath 'py' -ArgumentList @('-m','uvicorn','ai.main:app','--host','127.0.0.1','--port','8001','--reload') -WorkingDirectory $root -WindowStyle Normal | Out-Null
			Write-Host "AI service start command launched via 'py' (http://127.0.0.1:8001)"
		} catch {
			Write-Host "Failed to start uvicorn via 'py'. Trying 'python'..." -ForegroundColor Yellow
			try {
				Start-Process -FilePath 'python' -ArgumentList @('-m','uvicorn','ai.main:app','--host','127.0.0.1','--port','8001','--reload') -WorkingDirectory $root -WindowStyle Normal | Out-Null
				Write-Host "AI service start command launched via 'python' (http://127.0.0.1:8001)"
			} catch {
				Write-Host "Skipping AI service (could not launch uvicorn). Ensure Python and uvicorn are installed." -ForegroundColor Yellow
			}
		}
	} else {
		try {
			Start-Process -FilePath 'python' -ArgumentList @('-m','uvicorn','ai.main:app','--host','127.0.0.1','--port','8001','--reload') -WorkingDirectory $root -WindowStyle Normal | Out-Null
			Write-Host "AI service start command launched via 'python' (http://127.0.0.1:8001)"
		} catch {
			Write-Host "Skipping AI service (could not launch uvicorn). Ensure Python and uvicorn are installed." -ForegroundColor Yellow
		}
	}
}


$serverCmd = "cd '$root\server'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit","-Command",$serverCmd -WindowStyle Normal | Out-Null
Write-Host "Node backend start command launched (server on http://127.0.0.1:4000)"

$frontCmd = "cd '$root'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit","-Command",$frontCmd -WindowStyle Normal | Out-Null
Write-Host "Frontend start command launched (Vite, typically http://localhost:8080)"

Write-Host "All processes launched. Check the opened PowerShell windows for logs."
