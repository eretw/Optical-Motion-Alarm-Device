$ErrorActionPreference = 'Continue'
Write-Host 'Present serial ports (do not confuse software virtual ports with CH340):'
pnputil /enum-devices /connected /class Ports
Write-Host 'Serial registry map:'
reg query HKLM\HARDWARE\DEVICEMAP\SERIALCOMM
Write-Host 'If CH340 is missing: check USB_TTL, a data-capable cable, board power, JP5 and VM USB capture.'
