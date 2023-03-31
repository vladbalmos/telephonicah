from machine import UART
import uasyncio as asyncio

BAUDRATE = 115200

async def initialize(config = None):

    if config is None:
        config = {}
        
    if 'timeout' not in config:
        config['timeout'] = 50 #ms

    uart = UART(1)
    
    uart.init(baudrate=BAUDRATE, bits=8, parity=None, stop=1, tx=config['tx'], rx=config['rx'], timeout=config['timeout'], flow=0)
    reader = asyncio.StreamReader(uart)
    writer = asyncio.StreamWriter(uart)
    
    return reader, writer