if (!(Test-Path -Path src/index.html)) {
    Copy-Item -Path index.html.template -Destination src/index.html
}

if (!(Test-Path -Path src/phone_numbers.py)) {
    Copy-Item -Path phone_numbers.template -Destination src/phone_numbers.py
}

New-Item -ItemType Directory -Force -Path src/lib

if (!(Test-Path -Path src/lib/__init__.py)) {
    New-Item -ItemType File -Path src/lib/__init__.py
}

Copy-Item -Path lib/micropython-async/v3/primitives -Destination src/lib -Recurse -Force

Remove-Item -Path src/lib/primitives/tests -Recurse -Force