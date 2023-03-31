import machine
import uasyncio as asyncio
import json
import time
import sim800l
import os
import uart
from dynamic_queue import Queue
import phone_numbers
import led_notif
import webserver

SLEEP_MS = 50
RESET_SIM_COOLDOWN_S = 30

RST_PIN = 3
TX_PIN = 4
RX_PIN = 5
RED_LED_PIN = 6
GREEN_LED_PIN = 7
ENABLE_PIN = 8

wifi_status_sms_sent = False
last_reset = None

reset_pin = machine.Pin(RST_PIN, machine.Pin.OUT)
reset_pin.high()

enable_pin = machine.Pin(ENABLE_PIN, machine.Pin.OUT)
enable_pin.low()

state = {
    'gate_number': phone_numbers.GATE_NUMBER,
    'owner_number': phone_numbers.OWNER_NUMBER,
    'allowed_callers': phone_numbers.ALLOWED_CALLERS.copy(),
    'ssid': None,
    'ssid_password': None
}

available_commands = [
    'get:credit',
    'delete:sms',
    'reset:sim',
    'clear:state'
    'wifi:status',
    'wifi:connect\nssid\npassword'
]

async def sleep(ms = SLEEP_MS):
    return await asyncio.sleep_ms(ms)

async def _reset_sim():
    global last_reset

    reset_pin.low()
    await sleep(200)
    reset_pin.high()
    last_reset = time.ticks_ms()
    led_notif.toggle_red(False)
    webserver.logs_queue.put_nowait({'event': 'sim-reset'})

async def reset_sim():
    if not last_reset:
        print('Reseting SIM')
        return await _reset_sim()
    
    now = time.ticks_ms()
    diff = int(time.ticks_diff(now, last_reset) / 1000)
    
    if diff < RESET_SIM_COOLDOWN_S:
        return
    
    print('Reseting SIM')
    await _reset_sim()
    
async def toggle_enable_pin():
    print('Toggling ENABLE PIN')
    enable_pin.high()
    await sleep(50)
    enable_pin.low()

async def main():
    global state
    global wifi_status_sms_sent
    
    led = machine.Pin('LED', machine.Pin.OUT)
    red_led = machine.Pin(RED_LED_PIN, machine.Pin.OUT)
    green_led = machine.Pin(GREEN_LED_PIN, machine.Pin.OUT)
    
    led_notif.initialize(red_led, green_led)

    device_queue = Queue(24)
    debug_queue = Queue(24)
    command_queue = Queue(8)

    uart_config = {
        'tx': machine.Pin(TX_PIN, machine.Pin.OUT),
        'rx': machine.Pin(RX_PIN, machine.Pin.IN),
        'timeout': 250
    }
    
    reader, writer = await uart.initialize(uart_config)
    asyncio.create_task(sim800l.initialize(device_queue, debug_queue, reader, writer))
    
    try:
        with open('state.json', 'r') as state_file:
            contents = state_file.read()
            state = json.loads(contents)
    except Exception as e:
        print('No last state found')

    if state['ssid'] and state['ssid_password']:
        asyncio.create_task(webserver.initialize(command_queue, state, state['ssid'], state['ssid_password']))
        
    credit_info = ''
    last_credit_info_msg = None
        
    while True:
        led.toggle()
        
        if last_credit_info_msg:
            now = time.ticks_ms()
            diff = time.ticks_diff(now, last_credit_info_msg)
            if diff > 10 * 1000:
                asyncio.create_task(sim800l.send_sms_with_lock(state['owner_number'], credit_info))
                credit_info = ''
                last_credit_info_msg = None
            
        while not device_queue.empty():
            event = device_queue.get_nowait()
            log_event = True

            if event['event'] == 'incoming-event':
                log_event = False
                led_notif.start_blink_green(1000)
                print('device', event)
            elif event['event'] == 'outgoing-event':
                log_event = False
                led_notif.start_blink_green(3000)
                print('device', event)
            elif event['event'] == 'initializing':
                log_event = False
                led_notif.start_blink_red()
                print('device', event)
            elif event['event'] == 'sim-offline':
                led_notif.toggle_red(True)
                await reset_sim()
                print('device', event)
            elif event['event'] == 'initialized':
                log_event = False
                await led_notif.stop_blink_red()
            else:
                print('device', event)

            if log_event:
                webserver.logs_queue.put_nowait(event)
                
            if event['event'] == 'incoming-call':
                caller = event['caller']
                if caller in state['allowed_callers']:
                    asyncio.create_task(toggle_enable_pin())
                    asyncio.create_task(sim800l.open_gate(state['gate_number'], caller))
                else:
                    await sim800l.decline_call()
            
            if event['event'] == 'incoming-sms':
                if type(event['data']) is tuple and len(event['data']) == 3:
                    msg_details = event['data'][2] or []
                    msg_from_owner = False
                    msg_from_credit_info = False
                    for d in msg_details:
                        if state['owner_number'] in d:
                            msg_from_owner = True
                            break
                        if "Credit Info" in d:
                            msg_from_credit_info = True
                            break
                        
                    if msg_from_owner:
                        msg = event['data'][2]
                        msg = '\n'.join(msg[1:])
                        if msg:
                            msg = msg.lower().strip()
                        if msg == 'help:':
                            msg = '\n'.join(available_commands)
                            asyncio.create_task(sim800l.send_sms_with_lock(state['owner_number'], msg))
                        if msg == 'get:credit':
                            await sim800l.delete_sms(event['index'])
                            asyncio.create_task(sim800l.check_credit())
                        elif msg == 'delete:sms':
                            await sim800l.delete_sms(aquire_lock=True, delete_all=True)
                        elif msg == 'reset:sim':
                            print('Reseting SIM')
                            await _reset_sim()
                        elif msg == 'clear:state':
                            print('Clearing state and rebooting')
                            try:
                                os.remove('state.json')
                                print('State removed. Rebooting')
                                return machine.reset()
                            except:
                                print('No state to clear')
                        elif msg == 'wifi:status':
                            await sim800l.delete_sms(event['index'])
                            wifi_status, details = webserver.status()
                            msg = f'Status: {wifi_status}\n Details: {json.dumps(details)}'
                            asyncio.create_task(sim800l.send_sms_with_lock(state['owner_number'], msg))
                        elif 'wifi:connect' in msg:
                            await sim800l.delete_sms(event['index'])
                            segments = msg.split('\n')
                            if len(segments) != 3:
                                continue
                            
                            ssid = segments[1]
                            password = segments[2]
                            asyncio.create_task(webserver.initialize(command_queue, state, ssid, password))
                            print(f'Will connect to {ssid}/{password}')
                    elif msg_from_credit_info:
                        msg = event['data'][2]
                        msg = '\n'.join(msg[1:])
                        credit_info = f'{credit_info}{msg}'
                        last_credit_info_msg = time.ticks_ms()
                        await sim800l.delete_sms(event['index'])
                    else:
                        asyncio.create_task(sim800l.relay_sms(state['owner_number'], str(event['data']), event['index']))
                else:
                    await sim800l.relay_sms(state['owner_number'], str(event['data']), event['index'])
                    asyncio.create_task(sim800l.relay_sms(state['owner_number'], str(event['data']), event['index']))
                
        while not debug_queue.empty():
            info = debug_queue.get_nowait()
            webserver.logs_queue.put_nowait(info)
            print('debug', info)
            
        state_modified = False
        while not command_queue.empty():
            cmd = command_queue.get_nowait()
            print('command', cmd)
            webserver.logs_queue.put_nowait(cmd)
            if cmd['do'] == 'notif-wifi-connecting':
                led_notif.start_blink_red()
                
            if cmd['do'] == 'update-allowed-callers':
                new_dict = {}
                for name, number in cmd['payload']:
                    new_dict[name] = number
                state['allowed_callers'] = new_dict
                state_modified = True
            elif cmd['do'] == 'update-gate-number':
                state['gate_number'] = cmd['payload']
                state_modified = True
            elif cmd['do'] == 'update-owner-number':
                state['owner_number'] = cmd['payload']
                state_modified = True
            elif cmd['do'] == 'check-credit':
                asyncio.create_task(sim800l.check_credit())
            elif cmd['do'] == 'handle-wifi-status':
                await led_notif.stop_blink_red()
                result = cmd['payload']
                if result['status']:
                    state['ssid'] = result['ssid']
                    state['ssid_password'] = result['password']
                    state['ip'] = result['ip']
                    state['port'] = result['port']
                    state_modified = True
                    
                    ip = state['ip']
                    port = state['port']
                    msg = f'Connected: {ip}:{port}'
                else:
                    error_code = webserver.wifi_status_codes[result['code']]
                    msg = f'Unable to connect to wifi: {error_code}'
                    
                if not wifi_status_sms_sent:
                    # asyncio.create_task(sim800l.send_sms_with_lock(state['owner_number'], msg))
                    wifi_status_sms_sent = True
            else:
                continue
                
        if state_modified:
            try:
                with open('state.json', 'w') as state_file:
                    state_file.write(json.dumps(state))
            except Exception as e:
                print('Caught exception while writing state', e)
                webserver.logs_queue.put_nowait({'event': 'error', 'msg': f'Exception while writing state failed {e.args[0]}'})

        await sleep()
    
asyncio.run(main())
asyncio.new_event_loop()
