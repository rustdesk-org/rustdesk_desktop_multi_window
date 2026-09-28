param(
    [Parameter(Mandatory = $true)][string]$FlutterRoot,
    [Parameter(Mandatory = $true)][string]$Destination
)
$ErrorActionPreference = 'Stop'
$flutter = Join-Path $FlutterRoot 'bin/flutter.bat'
if (Test-Path -LiteralPath $Destination) {
    throw 'Use a new destination directory to avoid stale native build artifacts.'
}
$plugin = (Resolve-Path -LiteralPath "$PSScriptRoot/../..").Path.Replace('\', '/')
& $flutter create --platforms windows --project-name resize_probe --no-pub $Destination
if ($LASTEXITCODE -ne 0) { throw 'flutter create failed' }
@"
name: resize_probe
environment:
  sdk: '>=3.5.0 <4.0.0'
dependencies:
  flutter:
    sdk: flutter
  desktop_multi_window:
    path: '$plugin'
  url_launcher_windows: 3.1.4
  window_size:
    git:
      url: https://github.com/21pages/flutter-desktop-embedding.git
      ref: 51e67ce047c72b26810b99e8473ddb44612fe356
      path: plugins/window_size
  texture_rgba_renderer:
    git:
      url: https://github.com/rustdesk-org/flutter_texture_rgba_renderer
      ref: 42797e0f03141dc2b585f76c64a13974508058b4
flutter:
  uses-material-design: true
"@ | Set-Content -LiteralPath (Join-Path $Destination 'pubspec.yaml')
Copy-Item -LiteralPath "$PSScriptRoot/main.dart" -Destination (Join-Path $Destination 'lib/main.dart')
foreach ($name in @('check_windows.py', 'validate.py', 'stress.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $Destination
}
Push-Location -LiteralPath $Destination
try {
    & $flutter pub get
    if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed' }
} finally {
    Pop-Location
}
