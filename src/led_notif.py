import time
import uasyncio as asyncio

red_led = None
green_led = None
blink_tasks = {}

BLINK_TIMEOUT = 100

def initialize(rl, gl):
    global red_led
    global green_led
    
    red_led = rl
    green_led = gl
    
    red_led.value(False)
    green_led.value(False)
    
def toggle_led(led, force_value = None):
    if force_value:
        led.value(force_value)
        return

    if led.value():
        led.value(False)
        return
    
    led.value(True)
    
def toggle_red(force_value = None):
    toggle_led(red_led, force_value)
    
def toggle_green(force_value = None):
    toggle_led(green_led, force_value)
    
async def blink_led(led, duration = None, id = None):
    start = time.ticks_ms()
    while True:
        toggle_led(led)
        await asyncio.sleep_ms(BLINK_TIMEOUT)
        if duration and time.ticks_diff(time.ticks_ms(), start) > duration:
            led.value(False)
            del blink_tasks[id]
            return

    
def start_blink_red(duration = None):
    if 'red' in blink_tasks:
        return
    blink_tasks['red'] = asyncio.create_task(blink_led(red_led, duration, 'red'))

def start_blink_green(duration = None):
    if 'green' in blink_tasks:
        return
    blink_tasks['green'] = asyncio.create_task(blink_led(green_led, duration, 'green'))
    
async def stop_blink_red():
    if not 'red' in blink_tasks:
        return

    blink_tasks['red'].cancel()
    await asyncio.sleep_ms(50)
    red_led.value(False)
    del blink_tasks['red']

async def stop_blink_green():
    if not 'green' in blink_tasks:
        return

    blink_tasks['green'].cancel()
    await asyncio.sleep_ms(50)
    green_led.value(False)
    del blink_tasks['green']