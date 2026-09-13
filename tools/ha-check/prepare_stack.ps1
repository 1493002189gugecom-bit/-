[CmdletBinding()]
param(
    [string]$RepoRoot = (Join-Path $PSScriptRoot '..\..'),
    [switch]$RotateCredentials
)

$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 promotes a native command's stderr into a terminating
# error once $ErrorActionPreference is 'Stop', and Docker writes its progress to
# stderr. Every native call below therefore redirects stderr to $null and is
# validated through $LASTEXITCODE instead.
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

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$StandardInput
    )

    # Windows PowerShell 5.1 turns a native command's stderr into a terminating
    # error while $ErrorActionPreference is 'Stop', and Docker writes its build
    # progress to stderr. The preference is relaxed for the call instead, and the
    # exit code is checked explicitly by the caller.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($PSBoundParameters.ContainsKey('StandardInput')) {
            $StandardInput, $StandardInput | & $Command @Arguments 2>&1 | Out-Null
        }
        else {
            & $Command @Arguments 2>&1 | Out-Null
        }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
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

    # The password travels over stdin only, never as a command-line argument.
    $exitCode = Invoke-Native -Command 'docker' -Arguments $arguments -StandardInput $Password
    if ($exitCode -ne 0) {
        throw "mosquitto_passwd failed for user '$Username' (exit $exitCode)"
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

# The broker runs as an unprivileged user inside the container, so the hash file
# must be readable there. 0644 exposes only password hashes, never plaintext.
$runtimeDockerPathForChmod = $runtime.Replace('\', '/')
$chmodExit = Invoke-Native -Command 'docker' -Arguments @(
    'run', '--rm', '--volume', "${runtimeDockerPathForChmod}:/work",
    'eclipse-mosquitto:2', 'chmod', '644', '/work/password_file'
)
if ($chmodExit -ne 0) {
    throw "Could not make password_file readable for the broker (exit $chmodExit)"
}

$repoDockerPath = $RepoRoot.Replace('\', '/')
$composeEnv = @(
    "SHV_MOSQUITTO_CONFIG=$repoDockerPath/infra/home-assistant/mosquitto.conf"
    "SHV_MOSQUITTO_PASSWORD_FILE=$repoDockerPath/runtime/home-assistant/password_file"
    "SHV_ENV_FILE=$repoDockerPath/runtime/home-assistant/stack.env"
    "SHV_RUNTIME_DIR=$repoDockerPath/runtime/home-assistant"
) -join "`n"
Set-Content -Path (Join-Path $runtime 'compose.env') -Value $composeEnv -Encoding utf8

$buildExit = Invoke-Native -Command 'docker' -Arguments @(
    'build', '--tag', 'shv-device-simulator:local',
    (Join-Path $RepoRoot 'apps\device-simulator')
)
if ($buildExit -ne 0) {
    throw "Simulator image build failed (exit $buildExit)"
}
Write-Host 'Built shv-device-simulator:local.'
