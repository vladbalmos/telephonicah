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

# System requirements
* micropython
* ampy (pip3 install adafruit-ampy)
* minicom (optional)


# Development
Build micropython:

    cd [mycropython-dir]
    make -C mpy-cross

    cd [mycropython-dir]/ports/rp2
    make -j4 BOARD=PICO_W submodules
    make -j4 BOARD=PICO_W clean
    make -j4 BOARD=PICO_W
    
Init:

    ./setup.sh
    # edit src/phone_numbers.py and add phone numbers
    make build
    
Run:

    make run
    
Clean

    make clean
    
Upload

    make upload
    
Build

    make build
