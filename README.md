# UPDATE
The original version of this project is on branch `original-call-proxy`. The `master` branch doesn't forward calls to a designated number, instead it activates an external connected remote control using the signal port (see the schematic in the `hw` folder for the signal port pinout).
# Telephonicah

This repo contains firmware and hardware related resources (schematic, pcb & enclosure 3d models) for a device used to proxy GSM calls to a designated number (ex: parking barrier gate).

Hardware requirements:

    * Raspberry Pi Pico W
    * SIM800 GSM Module
    * 5V@2.5A power supply
    * capacitors: 100nf, 4.7uf, 2200uf
    * resistors: 2x150ohm, 1Mohm
    * leds: red, green
    
The Pico controls the SIM800 module via UART.

Features:

    * SMS based commands:
        * get remaining credit
        * delete SIM stored SMSs
        * connect to wifi
        * query wifi status
    * Relay received SMS to designated owner number
    * Web UI
    
After the devices connects to WIFI it will bind the webserver to port 8080 and a SMS containing the server's ip address and port will be sent to the administrator's phone number

# System requirements
* micropython
* ampy (pip3 install adafruit-ampy)
* minicom (optional)

# Development

## Linux
Build micropython:

    cd [mycropython-dir]
    make -C mpy-cross

    cd [mycropython-dir]/ports/rp2
    make -j4 BOARD=PICO_W submodules
    make -j4 BOARD=PICO_W clean
    make -j4 BOARD=PICO_W
    
After building copy the micropython firmware to a pico

Init:
    ./setup.sh
    # edit src/phone_numbers.py and add phone numbers
    make build
    
Run:

    make run
    
Clean

    make clean
    
Build

    make build

## Windows
Build micropython https://github.com/micropython/micropython/tree/master/ports/windows

After building copy the micropython firmware to a pico

Edit `build.ps1` and change the $PORT variable to the correct serial port (ex: com1)
Init:

    .\setup.ps1
    # edit src/phone_numbers.py and add phone numbers
    .\build.ps1 -Command build
    
Run:

    .\build.ps1 -Command run

Clean:

    .\build.ps1 -Command clean
    
Build:

    .\build.ps1 -Command build

List files on pico:

    .\build.ps1 -Command list
    
Copy file from pico:

    .\build.ps1 -Command get -Argument [filename]
    
Copy file to pico:

    .\build.ps1 -Command send -Argument [filename]