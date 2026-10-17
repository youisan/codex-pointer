$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $taskRoot
try {
    $taskVersion = (python -c "import sys; sys.path.insert(0, 'src'); from codex_pointer import __version__; print(__version__)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $taskVersion) { throw 'Could not determine package version.' }

    python scripts/make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'Icon asset generation failed.' }
    python scripts/sync_ui_icons.py
    if ($LASTEXITCODE -ne 0) { throw 'Launcher icon synchronization failed.' }
    python scripts/sync_launcher_translations.py
    if ($LASTEXITCODE -ne 0) { throw 'Launcher translation synchronization failed.' }

    # Collect notices from the installed community wheels before freezing. The
    # 6.7.0 wheels do not ship LGPL/GPL texts, so keep official copies in source.
    $taskDist = [System.IO.Path]::GetFullPath((Join-Path $taskRoot "dist\v$taskVersion"))
    $taskLicenses = Join-Path $taskDist 'THIRD_PARTY_LICENSES'
    New-Item -ItemType Directory -Force -Path $taskLicenses | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskRoot 'resources\licenses\LGPL-3.0.txt'),(Join-Path $taskRoot 'resources\licenses\GPL-3.0.txt') -Destination $taskLicenses -Force
    @'
from importlib import metadata
from pathlib import Path
import shutil
import sys
import PySide6
from PySide6.QtCore import qVersion

build_dist = Path(sys.argv[1])
destination = build_dist / 'THIRD_PARTY_LICENSES'
versions = {}
for name in ('PySide6', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'pyinstaller'):
    distribution = metadata.distribution(name)
    versions[name] = distribution.version
    for entry in distribution.files or ():
        parts = entry.parts
        if any(part.endswith('.dist-info') for part in parts) and any(
            marker in str(entry).lower() for marker in ('license', 'copying', 'notice')
        ):
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = destination / name / Path(*parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    # Preserve upstream licensing metadata, including copyrights and references.
    target = destination / name / 'METADATA.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(distribution.read_text('METADATA') or '', encoding='utf-8')

qt_version = qVersion()
binding_version = PySide6.__version__
notice = f'''Codex Pointer - third-party runtime notices

The Codex Pointer application source is MIT licensed (see LICENSE). This
does not change the licenses of the third-party components below.

This application uses the unmodified Qt for Python community distribution,
including PySide6 {binding_version}, Shiboken6 {versions['shiboken6']} and Qt
{qt_version}. The GUI uses Qt Core, GUI and Widgets libraries, with the Windows
platform, offscreen testing, JPEG and ICO image plugins. These
components are available under the GNU Lesser General Public License v3
(LGPLv3), together with the relevant upstream third-party notices. The LGPLv3
and referenced GPLv3 texts accompany this notice in THIRD_PARTY_LICENSES.
Some upstream wheel metadata also includes the alternative Qt commercial
license. Its inclusion does not grant a commercial license or replace the
open-source terms used by this distribution.

You may modify the LGPL-covered libraries and replace their corresponding
DLLs and bindings. Reverse engineering for debugging your modifications to
these libraries is permitted under their license. No project restriction is
intended to limit the rights granted by the LGPL.

The plugin ZIP contains a portable GUI with unpacked Qt DLLs and bindings in
plugins/codex-pointer/bin/_internal. Keep that directory next to its EXE.
Replace the relevant compatible libraries there with your modified build.
The separate single-file CodexPointer.exe is a convenience build: to use
modified Qt libraries, use the portable ZIP or rebuild it from the published
Codex Pointer source after installing the modified bindings. The executable
does not use static Qt linking or integrity checks to prohibit replacement.

Rebuild from the published Codex Pointer source on Windows with Python
3.10-3.12, then run:
  python -m pip install -e . pyinstaller
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build.ps1
For a modified PySide build, install it in the build environment instead of
the default wheel before running scripts/build.ps1. See the upstream build
instructions for supported compiler and Qt versions.

Exact unmodified upstream source and build instructions:
  Qt for Python {binding_version}:
    https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-{binding_version}-src/pyside-setup-everywhere-src-{binding_version}.zip
    https://code.qt.io/cgit/pyside/pyside-setup.git/
    https://doc.qt.io/qtforpython-6/building_from_source/index.html
  Qt {qt_version} (includes module-specific third-party attribution):
    https://download.qt.io/archive/qt/{'.'.join(qt_version.split('.')[:2])}/{qt_version}/single/qt-everywhere-src-{qt_version}.zip
    https://code.qt.io/cgit/qt/qtbase.git/?h=v{qt_version}

PyInstaller {versions['pyinstaller']} bundles the Python interpreter and
application code under its bootloader exception. Its upstream license
metadata is preserved in THIRD_PARTY_LICENSES. Python's bundled runtime
license is also included there.

Upstream licensing information:
  https://doc.qt.io/qtforpython-6/licenses.html
  https://www.qt.io/development/open-source-lgpl-obligations

Build dependency versions:
'''
notice += '\n'.join(f'  {name}: {version}' for name, version in versions.items()) + '\n'
(build_dist / 'THIRD_PARTY_NOTICES.txt').write_text(notice, encoding='utf-8')
python_license = Path(__import__('sys').base_prefix) / 'LICENSE.txt'
if python_license.is_file():
    shutil.copy2(python_license, destination / 'PYTHON-LICENSE.txt')
'@ | python - $taskDist
    if ($LASTEXITCODE -ne 0) { throw 'Third-party notice collection failed.' }

    $taskGuiArgs = @('--noconfirm', '--clean', '--windowed', '--name', 'CodexPointer', '--paths', 'src',
        '--additional-hooks-dir', 'scripts/pyinstaller-hooks',
        '--exclude-module', 'PyQt5', '--exclude-module', 'PyQt6', '--exclude-module', 'PySide2',
        '--exclude-module', 'tkinter', '--add-data', "$taskLicenses;THIRD_PARTY_LICENSES",
        '--add-data', "$(Join-Path $taskDist 'THIRD_PARTY_NOTICES.txt');.")
    $taskAssets = Join-Path $taskRoot 'src\codex_pointer\assets'
    if (Test-Path -LiteralPath $taskAssets) {
        $taskGuiArgs += @('--add-data', "$taskAssets;codex_pointer/assets")
        $taskIcon = Join-Path $taskAssets 'pointer.ico'
        if (Test-Path -LiteralPath $taskIcon) { $taskGuiArgs += @('--icon', $taskIcon) }
    }

    # The plugin carries replaceable dynamic Qt libraries; the standalone EXE
    # remains convenient for users who only need the desktop button.
    $taskPortable = Join-Path $taskDist 'portable'
    python -m PyInstaller @taskGuiArgs --onedir --distpath $taskPortable --workpath build/gui-portable run.py
    if ($LASTEXITCODE -ne 0) { throw 'Portable GUI build failed.' }
    $taskUnexpectedQt = Get-ChildItem -LiteralPath (Join-Path $taskPortable 'CodexPointer\_internal') -Recurse -File |
        Where-Object { $_.Name -match '^(Qt6(VirtualKeyboard|Pdf|Qml.*|Quick.*|Network|OpenGL.*)\.dll|opengl32sw\.dll|lib(ssl|crypto)-3-x64\.dll)$' }
    if ($taskUnexpectedQt) {
        throw "Unexpected optional Qt runtime collected: $($taskUnexpectedQt.Name -join ', '). Check custom widget hooks."
    }
    python -m PyInstaller @taskGuiArgs --onefile --distpath $taskDist --workpath build/gui-single run.py
    if ($LASTEXITCODE -ne 0) { throw 'Standalone GUI build failed.' }
    python -m PyInstaller --noconfirm --clean --onefile --console --name CodexPointerHost --icon "$taskAssets\pointer.ico" --paths src --distpath $taskDist --workpath build/mcp-host --add-data "$taskAssets\launcher.html;codex_pointer/assets" --exclude-module codex_pointer.app --exclude-module PySide6 --exclude-module shiboken6 --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module tkinter mcp_host.py
    if ($LASTEXITCODE -ne 0) { throw 'MCP host build failed.' }

    $taskBin = [System.IO.Path]::GetFullPath((Join-Path $taskRoot 'plugins\codex-pointer\bin'))
    $taskWorkspace = [System.IO.Path]::GetFullPath($taskRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
    if (-not $taskBin.StartsWith($taskWorkspace + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Generated plugin binary path escaped workspace.'
    }
    if (Test-Path -LiteralPath $taskBin) { Remove-Item -LiteralPath $taskBin -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $taskBin | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $taskPortable 'CodexPointer') -Force | Copy-Item -Destination $taskBin -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $taskDist 'CodexPointerHost.exe') -Destination $taskBin -Force
    Copy-Item -LiteralPath (Join-Path $taskDist 'THIRD_PARTY_NOTICES.txt') -Destination $taskBin -Force
    Copy-Item -LiteralPath $taskLicenses -Destination $taskBin -Recurse -Force

    $taskStage = [System.IO.Path]::GetFullPath((Join-Path $taskDist 'codex-pointer'))
    if (-not $taskStage.StartsWith($taskDist + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Release staging path escaped dist.'
    }
    if (Test-Path -LiteralPath $taskStage) { Remove-Item -LiteralPath $taskStage -Recurse -Force }
    $taskPluginDestination = Join-Path $taskStage 'plugins\codex-pointer'
    New-Item -ItemType Directory -Force -Path $taskPluginDestination | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $taskRoot 'plugins\codex-pointer') -Force | Copy-Item -Destination $taskPluginDestination -Recurse -Force
    $taskMarketplace = Join-Path $taskStage '.agents\plugins'
    New-Item -ItemType Directory -Force -Path $taskMarketplace | Out-Null
    Copy-Item -LiteralPath (Join-Path $taskRoot '.agents\plugins\marketplace.json') -Destination $taskMarketplace -Force
    Copy-Item -LiteralPath (Join-Path $taskRoot 'LICENSE'),(Join-Path $taskRoot 'README.md'),(Join-Path $taskRoot 'README.zh-CN.md'),(Join-Path $taskDist 'THIRD_PARTY_NOTICES.txt') -Destination $taskStage -Force
    $taskDocs = Join-Path $taskStage 'docs'
    New-Item -ItemType Directory -Force -Path $taskDocs | Out-Null
    foreach ($taskDocImage in @('preview-light.png', 'preview-dark.png', 'preview-light-en.png', 'preview-dark-en.png', 'preview-light-zh-CN.png', 'preview-dark-zh-CN.png', 'homepage-en.png', 'homepage-zh.png')) {
        Copy-Item -LiteralPath (Join-Path $taskRoot "docs\$taskDocImage") -Destination $taskDocs -Force
    }
    Copy-Item -LiteralPath $taskLicenses -Destination $taskStage -Recurse -Force
    $taskArchiveName = "codex-pointer-$taskVersion-windows-x64.zip"
    $taskArchive = Join-Path $taskDist $taskArchiveName
    Compress-Archive -Path $taskStage -DestinationPath $taskArchive -Force
    $taskArtifacts = @('CodexPointer.exe', 'CodexPointerHost.exe', $taskArchiveName)
    $taskHashes = foreach ($taskArtifact in $taskArtifacts) {
        $taskHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $taskDist $taskArtifact)).Hash.ToLowerInvariant()
        "$taskHash  $taskArtifact"
    }
    Set-Content -LiteralPath (Join-Path $taskDist 'SHA256SUMS.txt') -Encoding ASCII -Value $taskHashes
    Write-Output "Built $taskArchiveName with standalone GUI, portable GUI, and stdlib MCP host."
} finally {
    Pop-Location
}
