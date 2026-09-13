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
    # progress to stderr. The preference is relaxed and the output is captured so
    # the caller can report the real reason for a failure.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($PSBoundParameters.ContainsKey('StandardInput')) {
            $output = $StandardInput, $StandardInput | & $Command @Arguments 2>&1
        }
        else {
            $output = & $Command @Arguments 2>&1
        }
        return [pscustomobject]@{
            ExitCode = $LASTEXITCODE
            Output   = (($output | Out-String).Trim())
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
}

function Get-NativeFailureDetail {
    param([string]$Output)

    if ([string]::IsNullOrWhiteSpace($Output)) {
        return 'no output'
    }
    # mosquitto_passwd and docker never echo the credential, so the last line is
    # safe to surface and is the only useful diagnostic.
    return ($Output -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -Last 1)
}

function Remove-BrokerPasswordFile {
    <#
    Build into a fresh name and rename on the host afterwards. mosquitto_passwd -c
    refuses to overwrite an existing file, and a Docker Desktop bind mount keeps
    reporting a host-deleted file as still present inside the container.
    #>
    param([Parameter(Mandatory = $true)][string]$Target)

    $staging = Join-Path $runtime $Target
    if (Test-Path $staging -PathType Leaf) {
        Remove-Item -Force $staging
    }
    $runtimeDockerPath = $runtime.Replace('\', '/')
    $null = Invoke-Native -Command 'docker' -Arguments @(
        'run', '--rm', '--volume', "${runtimeDockerPath}:/work",
        'eclipse-mosquitto:2', 'rm', '-f', "/work/$Target"
    )
    if (Test-Path $staging -PathType Leaf) {
        throw "$Target still exists after removal; refusing to reuse stale credentials."
    }
}

function Invoke-MosquittoPasswd {
    param(
        [Parameter(Mandatory = $true)][string]$Username,
        [Parameter(Mandatory = $true)][string]$Password,
        [string]$Target = 'password_file',
        [switch]$Create
    )

    $runtimeDockerPath = $runtime.Replace('\', '/')
    # The password is written to a fresh file name. mosquitto_passwd -c refuses to
    # overwrite, and a Docker Desktop bind mount keeps reporting a host-deleted
    # file as existing inside the container, so reusing the final name is not
    # reliable. The caller renames the finished file into place.
    $arguments = @('run', '--rm', '-i', '--volume', "${runtimeDockerPath}:/work", 'eclipse-mosquitto:2', 'mosquitto_passwd')
    if ($Create) {
        $arguments += '-c'
    }
    $arguments += @("/work/$Target", $Username)

    # The password travels over stdin only, never as a command-line argument.
    $result = Invoke-Native -Command 'docker' -Arguments $arguments -StandardInput $Password
    if ($result.ExitCode -ne 0) {
        throw "mosquitto_passwd failed for user '$Username' (exit $($result.ExitCode)): $(Get-NativeFailureDetail $result.Output)"
    }
}

$passwordFile = Join-Path $runtime 'password_file'
$stackEnvFile = Join-Path $runtime 'stack.env'
$passwordFileExists = Test-Path $passwordFile -PathType Leaf
$stackEnvFileExists = Test-Path $stackEnvFile -PathType Leaf

if ($passwordFileExists -xor $stackEnvFileExists) {
    if (-not $RotateCredentials) {
        throw 'Credential state is incomplete: password_file and stack.env must either both exist or both be absent. Pass -RotateCredentials to regenerate both.'
    }
    # Rotation rewrites both files, so an interrupted earlier rotation is
    # recoverable instead of leaving the operator stuck.
    Write-Host 'Credential state is incomplete; regenerating both files.'
}

if (-not $passwordFileExists -or $RotateCredentials) {
    $haPassword = New-RandomPassword
    $simPassword = New-RandomPassword
    while ($simPassword -eq $haPassword) {
        $simPassword = New-RandomPassword
    }

    # Build into a fresh name, then move it into place on the host.
    $stagingName = 'password_file.new'
    Remove-BrokerPasswordFile -Target $stagingName
    Invoke-MosquittoPasswd -Username 'homeassistant' -Password $haPassword -Target $stagingName -Create
    Invoke-MosquittoPasswd -Username 'simulator' -Password $simPassword -Target $stagingName

    # The broker runs as an unprivileged user inside the container, so the hash
    # file must be readable there. 0644 exposes only hashes, never plaintext.
    $runtimeDockerPathForChmod = $runtime.Replace('\', '/')
    $chmodResult = Invoke-Native -Command 'docker' -Arguments @(
        'run', '--rm', '--volume', "${runtimeDockerPathForChmod}:/work",
        'eclipse-mosquitto:2', 'chmod', '644', "/work/$stagingName"
    )
    if ($chmodResult.ExitCode -ne 0) {
        throw "Could not make the password file readable for the broker: $(Get-NativeFailureDetail $chmodResult.Output)"
    }

    $stagingPath = Join-Path $runtime $stagingName
    if (-not (Test-Path $stagingPath -PathType Leaf)) {
        throw "mosquitto_passwd reported success but $stagingName was not created."
    }
    if (Test-Path $passwordFile -PathType Leaf) {
        Remove-Item -Force $passwordFile
    }
    Move-Item -Force $stagingPath $passwordFile

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

$buildResult = Invoke-Native -Command 'docker' -Arguments @(
    'build', '--tag', 'shv-device-simulator:local',
    (Join-Path $RepoRoot 'apps\device-simulator')
)
if ($buildResult.ExitCode -ne 0) {
    throw "Simulator image build failed: $(Get-NativeFailureDetail $buildResult.Output)"
}
Write-Host 'Built shv-device-simulator:local.'
