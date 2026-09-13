[CmdletBinding()]
param(
    [string]$RepoRoot = (Join-Path $PSScriptRoot '..\..'),
    [switch]$RotateCredentials
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path $RepoRoot).Path
$runtime = Join-Path $RepoRoot 'runtime\home-assistant'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function New-RandomPassword {
    param([int]$Length = 32)

    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    $builder = New-Object System.Text.StringBuilder
    $buffer = New-Object byte[] 64
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        while ($builder.Length -lt $Length) {
            $rng.GetBytes($buffer)
            foreach ($value in $buffer) {
                # 248 is the largest multiple of 62 below 256; rejection avoids modulo bias.
                if ($value -lt 248) {
                    [void]$builder.Append($alphabet[$value % $alphabet.Length])
                    if ($builder.Length -eq $Length) {
                        break
                    }
                }
            }
        }
        return $builder.ToString()
    }
    finally {
        $rng.Dispose()
    }
}

function Invoke-MosquittoPasswd {
    param(
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$Password,
        [switch]$Create
    )

    $runtimeDockerPath = $runtime.Replace('\', '/')
    $arguments = @('run', '--rm', '-i', '--volume', "${runtimeDockerPath}:/work", 'eclipse-mosquitto:2', 'mosquitto_passwd')
    if ($Create) {
        $arguments += '-c'
    }
    $arguments += @('/work/password_file', $Username)

    $Password, $Password | & docker @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "mosquitto_passwd failed for user '$Username' (exit $LASTEXITCODE)"
    }
}

$passwordFile = Join-Path $runtime 'password_file'
$stackEnvFile = Join-Path $runtime 'stack.env'
$passwordFileExists = Test-Path $passwordFile -PathType Leaf
$stackEnvFileExists = Test-Path $stackEnvFile -PathType Leaf

if ($passwordFileExists -xor $stackEnvFileExists) {
    throw 'Credential state is incomplete: password_file and stack.env must either both exist or both be absent.'
}

if (-not $passwordFileExists -or $RotateCredentials) {
    $haPassword = New-RandomPassword
    $simPassword = New-RandomPassword
    while ($simPassword -eq $haPassword) {
        $simPassword = New-RandomPassword
    }

    if ($passwordFileExists) {
        Remove-Item -Force $passwordFile
    }
    Invoke-MosquittoPasswd -Username 'homeassistant' -Password $haPassword -Create
    Invoke-MosquittoPasswd -Username 'simulator' -Password $simPassword

    $stackEnv = @(
        'MQTT_USERNAME=simulator'
        "MQTT_PASSWORD=$simPassword"
        'MQTT_HA_USERNAME=homeassistant'
        "MQTT_HA_PASSWORD=$haPassword"
    ) -join "`n"
    Set-Content -Path $stackEnvFile -Value $stackEnv -Encoding utf8
    Write-Host 'Generated local MQTT credentials (values not displayed).'
}
else {
    Write-Host 'Reusing existing local MQTT credentials (values not read or displayed).'
}

$repoDockerPath = $RepoRoot.Replace('\', '/')
$composeEnv = @(
    "SHV_MOSQUITTO_CONFIG=$repoDockerPath/infra/home-assistant/mosquitto.conf"
    "SHV_MOSQUITTO_PASSWORD_FILE=$repoDockerPath/runtime/home-assistant/password_file"
    "SHV_ENV_FILE=$repoDockerPath/runtime/home-assistant/stack.env"
    "SHV_RUNTIME_DIR=$repoDockerPath/runtime/home-assistant"
) -join "`n"
Set-Content -Path (Join-Path $runtime 'compose.env') -Value $composeEnv -Encoding utf8

& docker build --tag 'shv-device-simulator:local' (Join-Path $RepoRoot 'apps\device-simulator')
if ($LASTEXITCODE -ne 0) {
    throw "Simulator image build failed (exit $LASTEXITCODE)"
}
Write-Host 'Built shv-device-simulator:local.'
