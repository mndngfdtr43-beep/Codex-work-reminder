param(
    [string]$ArduinoCli = '',
    [string]$Port = '',
    [switch]$Upload,
    [ValidateSet(48, 38)][int]$OnboardPin = 48
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if (-not $ArduinoCli) {
    $command = Get-Command arduino-cli -ErrorAction SilentlyContinue
    if ($command) { $ArduinoCli = $command.Source }
    else {
        $candidates = @()
        if ($env:ProgramFiles) {
            $candidates += Join-Path $env:ProgramFiles 'Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe'
        }
        if ($env:LOCALAPPDATA) {
            $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe'
        }
        $ArduinoCli = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $ArduinoCli) { throw '找不到 arduino-cli，请用 -ArduinoCli 指定可执行文件。' }
    }
}
$libraryDir = Join-Path $projectRoot '.tools\libraries'
$library = Join-Path $libraryDir 'Adafruit_NeoPixel-1.15.2'
if (-not (Test-Path -LiteralPath $library)) {
    New-Item -ItemType Directory -Path $libraryDir -Force | Out-Null
    $zipFile = Join-Path $projectRoot '.tools\Adafruit_NeoPixel-1.15.2.zip'
    Invoke-WebRequest -Uri 'https://downloads.arduino.cc/libraries/github.com/adafruit/Adafruit_NeoPixel-1.15.2.zip' -OutFile $zipFile
    Expand-Archive -LiteralPath $zipFile -DestinationPath $libraryDir -Force
}
$fixedBootloader = Join-Path $projectRoot 'build\bootloader-xmc207018.bin'
$idfPython = Join-Path $projectRoot '.tools\idf-venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $fixedBootloader) -or -not (Test-Path -LiteralPath $idfPython)) {
    python -X utf8 (Join-Path $PSScriptRoot 'setup_bootloader.py')
    if ($LASTEXITCODE -ne 0) { throw 'XMC 引导程序构建失败，未烧录原版引导程序。' }
}
# Use UART bridge connector. CDC disabled intentionally; PSRAM is unused.
$fqbn = 'esp32:esp32:esp32s3:CDCOnBoot=default,FlashMode=dio,FlashSize=16M,PartitionScheme=default,PSRAM=disabled'
$ledPin = $OnboardPin
$ledCount = 1
$ledBrightness = 32
Write-Host "Onboard RGB LED: GPIO $ledPin, count $ledCount"
& $ArduinoCli compile --fqbn $fqbn --build-property "compiler.cpp.extra_flags=-DCAR_LED_PIN=$ledPin -DCAR_LED_COUNT=$ledCount -DCAR_BRIGHTNESS=$ledBrightness" --libraries $libraryDir --output-dir (Join-Path $projectRoot 'build\firmware') (Join-Path $projectRoot 'firmware\ai_status_light')
if ($LASTEXITCODE -ne 0) { throw '固件编译失败，未执行烧录。' }
$outputDir = Join-Path $projectRoot 'build\firmware'
Copy-Item -LiteralPath $fixedBootloader -Destination (Join-Path $outputDir 'ai_status_light.ino.bootloader.bin') -Force
$bootApp = Join-Path $env:LOCALAPPDATA 'Arduino15\packages\esp32\hardware\esp32\3.3.12\tools\partitions\boot_app0.bin'
if (-not (Test-Path -LiteralPath $bootApp)) { throw '请安装本项目验证过的 ESP32 core 3.3.12。' }
& $idfPython -m esptool --chip esp32s3 merge_bin -o (Join-Path $outputDir 'ai_status_light.ino.merged.bin') --flash_mode dio --flash_freq 80m --flash_size 16MB 0x0 (Join-Path $outputDir 'ai_status_light.ino.bootloader.bin') 0x8000 (Join-Path $outputDir 'ai_status_light.ino.partitions.bin') 0xe000 $bootApp 0x10000 (Join-Path $outputDir 'ai_status_light.ino.bin')
if ($LASTEXITCODE -ne 0) { throw '适配固件合并失败，未执行烧录。' }
if ($Upload) {
    if (-not $Port) { throw '烧录必须通过 -Port COMxx 显式指定状态灯开发板。' }
    & $ArduinoCli upload --fqbn $fqbn --port $Port --input-dir (Join-Path $projectRoot 'build\firmware') (Join-Path $projectRoot 'firmware\ai_status_light')
    if ($LASTEXITCODE -ne 0) { throw '烧录失败，请检查串口、数据线和下载模式。' }
    & $idfPython -X utf8 (Join-Path $PSScriptRoot 'verify_board.py') --port $Port --expect-led-pin $ledPin --expect-led-count $ledCount
    if ($LASTEXITCODE -ne 0) { throw '写入完成但实物启动/通信验证失败，请查看串口诊断。' }
}
