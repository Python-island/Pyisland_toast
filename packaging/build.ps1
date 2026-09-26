# Build a windowed Nuitka folder. Onefile is not used: it unpacks on every launch.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$frontend = Join-Path $root "toast_frontend\frontend"
$distFrontend = Join-Path $frontend "dist"
foreach ($name in @("index.html", "ai.html", "settings.html")) {
    $page = Join-Path $distFrontend $name
    if (-not (Test-Path -LiteralPath $page)) {
        Push-Location $frontend
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        Pop-Location
        break
    }
}

$icon = Join-Path $root "pyisland_toast\ico\PyislandLogo.ico"
$example = Join-Path $root "pyisland_toast\ai_config.example.json"
foreach ($path in @($icon, $example, (Join-Path $distFrontend "index.html"), (Join-Path $distFrontend "ai.html"), (Join-Path $distFrontend "settings.html"))) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing $path"
    }
}

$work = Join-Path $root "build\nuitka"
New-Item -ItemType Directory -Force -Path $work | Out-Null
$icoDir = Join-Path $root "pyisland_toast\ico"

$nuitkaArgs = @(
    "-m", "nuitka",
    "--standalone",
    "--deployment",
    "--assume-yes-for-downloads",
    "--remove-output",
    "--msvc=latest",
    "--enable-plugin=pyside6",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=$icon",
    "--company-name=Pyisland",
    "--product-name=Pyisland_toast",
    "--file-version=0.1.0.0",
    "--product-version=0.1.0",
    "--output-dir=$work",
    "--output-filename=Pyisland_toast.exe",
    "--include-data-dir=$distFrontend=toast_frontend/frontend/dist",
    "--include-data-dir=$icoDir=pyisland_toast/ico",
    "--include-data-files=$example=pyisland_toast/ai_config.example.json",
    "--include-module=PySide6.QtWebEngineCore",
    "--include-module=PySide6.QtWebEngineWidgets",
    "--include-module=PySide6.QtWebChannel",
    "--include-module=qasync",
    "--include-package=pyisland_toast",
    "--include-package=win11toast",
    "--include-package=windows_bluetooth_watcher",
    "--include-package=winrt.windows.foundation",
    "--include-package=winrt.windows.foundation.collections",
    "--include-package=winrt.windows.ui.notifications",
    "--include-package=winrt.windows.ui.notifications.management",
    "--include-package=winrt.windows.data.xml.dom",
    "--nofollow-import-to=pytest",
    "--nofollow-import-to=pigar",
    "--nofollow-import-to=pyinstaller",
    "--nofollow-import-to=nuitka",
    "--nofollow-import-to=winrt.windows.media",
    "--nofollow-import-to=winrt.windows.graphics",
    "--nofollow-import-to=winrt.windows.storage",
    "--nofollow-import-to=winrt.windows.globalization",
    "--noinclude-data-files=*/ai_config.json",
    "--python-flag=no_docstrings",
    "--python-flag=no_asserts",
    "--show-progress",
    (Join-Path $root "packaging\launch_pyisland.py")
)

& uv run --no-dev --with nuitka python @nuitkaArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$built = Get-ChildItem -LiteralPath $work -Directory -Filter "*.dist" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $built) { throw "Nuitka did not create a .dist directory in $work" }

$finalParent = Join-Path $root "dist"
$final = Join-Path $finalParent "Pyisland_toast"
New-Item -ItemType Directory -Force -Path $finalParent | Out-Null
if (Test-Path -LiteralPath $final) {
    Remove-Item -LiteralPath $final -Recurse -Force
}
Move-Item -LiteralPath $built.FullName -Destination $final

Copy-Item -LiteralPath $example -Destination (Join-Path $final "ai_config.example.json") -Force
$secret = Join-Path $final "ai_config.json"
if (Test-Path -LiteralPath $secret) {
    Remove-Item -LiteralPath $secret -Force
}

$required = @(
    "Pyisland_toast.exe",
    "ai_config.example.json",
    "pyisland_toast\ico\PyislandLogo.ico",
    "toast_frontend\frontend\dist\index.html",
    "toast_frontend\frontend\dist\ai.html",
    "toast_frontend\frontend\dist\settings.html"
)
foreach ($rel in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $final $rel))) {
        throw "Packaged file is missing: $rel"
    }
}
if (Test-Path -LiteralPath $secret) { throw "ai_config.json must not be packaged" }
$web = Get-ChildItem -LiteralPath $final -Recurse -Filter "QtWebEngineProcess.exe" | Select-Object -First 1
if (-not $web) { throw "QtWebEngineProcess.exe was not packaged" }
Get-ChildItem -LiteralPath $final -Recurse -Filter "*.debug.pak" | Remove-Item -Force

Write-Output "Built $final"
Write-Output "Copy ai_config.example.json to ai_config.json beside the exe before first launch."
