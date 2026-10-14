param(
    [Parameter(Mandatory=$true)][string]$RequestPath,
    [Parameter(Mandatory=$true)][string]$ReportPath,
    [Parameter(Mandatory=$true)][string]$CancelPath,
    [string]$TestFixturePath = ''
)
$ErrorActionPreference = 'Stop'
$runnerReport = $ReportPath
$runnerCancel = $CancelPath
$runnerFixture = $TestFixturePath
$request = Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$numbers = @($request.Stations)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
. (Join-Path $PSScriptRoot 'LovionCoordinateTool.Gui.ps1')
$script:StationTestReportPath = $runnerReport
$script:StationTestRequested = $numbers
$script:LovionBatchLogPath = [IO.Path]::ChangeExtension($runnerReport, '.log')
$script:RunnerManual = @()
$script:RunnerPlanned = @()
function Send-RunnerEvent([string]$Type, [string]$Message, [string]$Station = '') {
    [Console]::WriteLine((@{type=$Type; message=$Message; station=$Station} | ConvertTo-Json -Compress))
}
function Set-LovionBatchStatus([string]$Message) { Send-RunnerEvent 'progress' $Message }
function Write-LovionBatchLog([string]$Message) {
    [IO.File]::AppendAllText($script:LovionBatchLogPath, ($Message + [Environment]::NewLine), (New-Object Text.UTF8Encoding($false)))
    Send-RunnerEvent 'log' $Message
}
function Assert-LovionAutomationNotCancelled {
    if (Test-Path -LiteralPath $runnerCancel) { throw 'Gestopt op verzoek van de gebruiker.' }
    if (-not $runnerFixture -and [LovionBatchInput]::IsMouseGuardCancelled()) {
        throw 'Gestopt omdat de muis werd bewogen.'
    }
}
function Write-RunnerReport([string]$State, [string]$ErrorMessage = '') {
    Write-LovionStationTestCheckpoint -State $State -ErrorMessage $ErrorMessage
    $saved = Get-Content -LiteralPath $runnerReport -Raw -Encoding UTF8 | ConvertFrom-Json
    $saved | Add-Member NoteProperty ManualStations @($script:RunnerManual)
    $saved | Add-Member NoteProperty PlannedTransformers @($script:RunnerPlanned)
    [IO.File]::WriteAllText($runnerReport, ($saved | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
}
# Fixture execution exercises the upstream multi-transformer workflow without
# hooks, clicks, keyboard input, clipboard access or OCR. Never exposed in UI.
if ($runnerFixture) {
    $script:Fixture = Get-Content -LiteralPath $runnerFixture -Raw -Encoding UTF8 | ConvertFrom-Json
    [void]$script:Table.Columns.Add('Master Asset ID')
    [void]$script:Table.Columns.Add('SourceFile')
    function Open-LovionConnectionsForStation {
        param($StationNumber, $StationIndex, $StationCount, $TransformerIndex, $KnownTransformerCount, $ReuseCurrentStationResults)
        Assert-LovionAutomationNotCancelled
        $script:FixtureStation = $StationNumber
        $trafos = @($script:Fixture.$StationNumber)
        $script:FixtureTrafo = $trafos[$TransformerIndex]
        $failure = Get-ObjectPropertyValue $script:FixtureTrafo 'Error'
        $delay = Get-ObjectPropertyValue $script:FixtureTrafo 'Delay'
        $status = Get-ObjectPropertyValue $script:FixtureTrafo 'Status'
        if ($failure) { throw $failure }
        if ($delay) { Start-Sleep -Milliseconds $delay; Assert-LovionAutomationNotCancelled }
        return [pscustomobject]@{InitialResultCount=$trafos.Count; TransformerStatus=$status;
            SkipReason=$(if ($status -eq 'gepland') {'gepland'} else {''});
            ManualRequired=[bool](Get-ObjectPropertyValue $script:FixtureTrafo 'Manual');
            ConnectionCount=@(Get-ObjectPropertyValue $script:FixtureTrafo 'Assets').Count}
    }
    function Invoke-LovionBatchImport {
        param($SourcePrefix, [switch]$SkipCountdown, [switch]$UseExactSourceName, $SourceType)
        $assets = @(Get-ObjectPropertyValue $script:FixtureTrafo 'Assets')
        foreach ($asset in $assets) {
            $row = $script:Table.NewRow(); $row['Master Asset ID'] = [string]$asset; $row['SourceFile'] = $SourcePrefix
            $script:Table.Rows.Add($row)
        }
        return @{ImportedCount=$assets.Count}
    }
    function Close-LovionStationResultTabs {}
    function Invoke-LovionStationClick { param($X,$Y,$WaitMilliseconds,$Description) }
    function Wait-LovionScreenPattern { param($Pattern,$TimeoutSeconds,$Description) return $true }
}
$exitCode = 0
try {
    Write-RunnerReport 'starting'
    if (-not $runnerFixture) {
        [LovionBatchInput]::EnableDpiAwareness()
        for ($seconds=5; $seconds -gt 0; $seconds--) {
            Assert-LovionAutomationNotCancelled
            Send-RunnerEvent 'progress' "Start over $seconds seconden. LOVION moet zichtbaar zijn."
            Start-Sleep -Seconds 1
        }
    }
    foreach ($station in $numbers) {
        Assert-LovionAutomationNotCancelled
        Send-RunnerEvent 'station_started' "Station $station verwerken" $station
        $result = if ($runnerFixture) { Invoke-LovionStationsImportCore -StationNumbers @($station) }
                  else { Invoke-LovionStationsImport -StationNumbers @($station) }
        $script:RunnerManual += @($result.ManualStations)
        $script:RunnerPlanned += @($result.PlannedTransformers)
        Write-RunnerReport 'running'
        Send-RunnerEvent 'station_finished' "Station $station verwerkt" $station
    }
    Write-RunnerReport 'complete'
} catch {
    $exitCode = 1
    $message = $_.Exception.Message
    Write-RunnerReport 'failed' $message
    Send-RunnerEvent 'error' $message
} finally {
    if (-not $runnerFixture) { [LovionBatchInput]::ReleaseModifiers(); [LovionBatchInput]::StopMouseGuard() }
}
exit $exitCode
