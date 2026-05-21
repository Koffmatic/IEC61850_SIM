# Run this PowerShell script as Administrator.
# Each simulated IED requires its own local IP alias on the same adapter.

$adapterName = "Ethernet"
$prefixLength = 24
$ipAddresses = @(
    "10.206.204.5",
    "10.206.204.16",
    "10.206.204.17"
)

foreach ($ipAddress in $ipAddresses) {
    if ([string]::IsNullOrWhiteSpace($ipAddress)) {
        continue
    }

    $existingIp = Get-NetIPAddress -InterfaceAlias $adapterName -IPAddress $ipAddress -ErrorAction SilentlyContinue

    if ($null -ne $existingIp) {
        Write-Host "$ipAddress already exists on $adapterName"
        continue
    }

    New-NetIPAddress -InterfaceAlias $adapterName -IPAddress $ipAddress -PrefixLength $prefixLength -AddressFamily IPv4
    Write-Host "Added $ipAddress to $adapterName"
}
