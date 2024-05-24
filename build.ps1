param (
    [Parameter(Mandatory=$true)]
    [string]$Command,
    [string]$Argument
)

$SRC_DIR = "src"
$PORT = "com3"


function send-everything {
    ampy --port $PORT put $SRC_DIR /
}

function send-src {
    Get-ChildItem -Path $SRC_DIR -File | ForEach-Object {
        ampy --port $PORT put $($SRC_DIR + "/" + $_.Name)
    }
}

function reset {
    ampy --port $PORT reset --hard
}

function clean {
    ampy --port $PORT ls -r | ForEach-Object {
        ampy --port $PORT rm $_
    }
    ampy --port $PORT rm lib/primitives
    ampy --port $PORT rm lib
}

function run {
    send-src
    reset
}

function list {
    ampy --port $PORT ls -r
}

function build {
    send-everything
    reset
}

function get {
    param (
        [Parameter(Mandatory=$true)]
        [string]$Filename
    )
    ampy --port $PORT get $Filename
}

function send {
    param (
        [Parameter(Mandatory=$true)]
        [string]$Filename
    )
    ampy --port $PORT put $Filename
}

switch ($Command) {
    "send-everything" { send-everything } # upload everything to pico
    "send-src" { send-src } # upload only src files to pico
    "reset" { reset } # reset pico
    "clean" { clean } # delete all files on pico
    "run" { run } # upload only src files and reset pico
    "list" { list } # list all files on pico
    "build" { build } # upload everything and reset pico
    "get" { get $Argument } # retrieve file from pico
    "send" { send $Argument } # retrieve file from pico
    default { Write-Host "Check build.ps1 for available commands" }
}