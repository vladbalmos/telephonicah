import uasyncio as asyncio
import time
import os
from dynamic_queue import Queue

SLEEP_MS = 50
MAX_LOCK_DURATION_S = 30

device_queue = None
debug_queue = None
debug_mode = False
reader = None
writer = None

write_queue = Queue(24)
read_queue = Queue(24)
urc_queue = Queue(24)

pin_set = False
pin_timeout_count = 0
pin_query_fail_count = 0
caller = None
incoming_call_in_progress = False

callee = None
outgoing_call_in_progress = False
outgoing_operation_in_progress = False

first_ring_event = asyncio.Event()
first_ring_event.set()

gate_ring_ok = False
gate_last_urc = None

last_state = {
    'network': None,
    'signal': None,
    'signal_friendly': None,
    'pin_status': None,
    'product': None,
    'product_details': None
}

URC = [
    '+CLIP',
    '+CPIN',
    'SMS Ready',
    'Call Ready',
    '+CMTI',
    '+CDRIND',
    'RING',
    'MO RING',
    'MO CONNECTED',
    'BUSY',
    'NO CARRIER',
    'NO DIALTONE',
    'NO ANSWER',
    'NORMAL POWER DOWN',
    'UNDER-VOLTAGE POWER DOWN',
    'UNDER-VOLTAGE WARNING',
    'OVER-VOLTAGE POWER DOWN',
    'OVER-VOLTAGE WARNING',
    'CHARGE-ONLY MODE',
    'RDY'
]

ignore_urc_list = [
    'RING',
    '+CPIN',
    'SMS Ready',
    'Call Ready',
    'CHARGE-ONLY MODE',
    'RDY'
]

line_buffer = []

uart_lock = asyncio.Lock()
command_lock = asyncio.Lock()
write_lock = asyncio.Lock()
last_command = None

def is_busy():
    # print(incoming_call_in_progress, outgoing_call_in_progress, outgoing_operation_in_progress)
    return incoming_call_in_progress or outgoing_call_in_progress or outgoing_operation_in_progress
    
async def sleep(ms = SLEEP_MS):
    return await asyncio.sleep_ms(ms)

def is_unsolicited(msg):
    segments = msg.split(':')
    code = segments.pop(0)
    
    if code in ('+CDRIND', 'BUSY', 'NO CARRIER', 'NO ANSWER', 'NO DIALTONE'):
        if last_command == 'ATH':
            return False
        
    if code == '+CPIN' and last_command == 'AT+CPIN?':
        return False
    
    return code in URC

async def send_sms(number, message):
    print('sending sms to', number, message)
    await send('AT+CMGF=1')
    await send(f'AT+CMGS="{number}"', no_wait=True)
    sms = message + '\r\n' + chr(26)
    await send(sms, timeout=30)
    
async def send_sms_with_lock(number, message):
    device_queue.put_nowait({'event': 'outgoing-event'})
    async with uart_lock:
        await send_sms(number, message)
    
async def delete_sms(index = 1, aquire_lock = True, delete_all = False):
    if delete_all:
        del_flag = 4
    else:
        del_flag = 0
        
    if aquire_lock:
        async with uart_lock:
            await send(f'AT+CMGD={index},{del_flag}')
            return
        
    await send(f'AT+CMGD={index},{del_flag}')
    
async def relay_sms(number, message, msg_index):
    print('relaying sms to', number, message, msg_index)
    global outgoing_operation_in_progress
    async with uart_lock:
        outgoing_operation_in_progress = True
        await delete_sms(msg_index, aquire_lock=False)
        await send_sms(number, message)
        outgoing_operation_in_progress = False
        
async def check_credit():
    global outgoing_operation_in_progress
    await sleep(1000)
    async with uart_lock:
        outgoing_operation_in_progress = True
        print('calling credit info number')
        await send('ATD333;')
        outgoing_operation_in_progress = False
        
    
async def call_gate(number, caller):
    global outgoing_call_in_progress
    global callee
    global gate_ring_ok

    first_ring_event.clear()

    outgoing_call_in_progress = True
    callee = number

    max_retries = 3
    retry_counter = 0
    
    failed_message = None
    log_messages = [f'Starting gate {number} call procedure for {caller}']

    try:
        
        while True:
            if retry_counter >= max_retries:
                log_messages.append(f'{time.ticks_ms()} Reached retry limit. Calling failed')
                break

            device_queue.put_nowait({'event': 'outgoing-event'})
            log_messages.append(f'{time.ticks_ms()} Calling gate')
            call_cmd_status, call_status, call_result = await send(f'ATD{number};')
            
            if call_status != 'OK':
                retry_counter += 1
                first_ring_event.set()
                failed_message = f'Unable to call gate. Reason {call_cmd_status}, {call_status}, {str(call_result)}'
                log_messages.append(f'{time.ticks_ms()} Calling failed: {failed_message}')
                await sleep()
                continue

            log_messages.append(f'{time.ticks_ms()} Waiting for first ring')
            await asyncio.wait_for(first_ring_event.wait(), 30)
            await sleep(500)

            log_messages.append(f'{time.ticks_ms()} Last URC: {gate_last_urc}')
            
            if gate_ring_ok:
                log_messages.append(f'{time.ticks_ms()} Gate response is OK. Canceling ringing')
                print("Gate response is OK")
                _, _, result = await send('ATH', timeout=2, expect_single_line_response=False)
                await handle_call_ending(result)
                gate_ring_ok = False
                failed_message = None
                break
            
            log_messages.append(f'{time.ticks_ms()} Gate response is invalid. Retrying')

            retry_counter += 1
            print("Gate response is invalid. Retrying...")
    except asyncio.TimeoutError:
        first_ring_event.set()
        log_messages.append(f'{time.ticks_ms()} Timeout occured while waiting to first ring');
        print('Timeout occured while waiting to first ring')
        failed_message = 'Timeout occured while waiting for first ring'
        debug_queue.put_nowait({'event': 'error', 'msg': 'Timeout occured while waiting for first ring'})
    finally:
        outgoing_call_in_progress = False

    if failed_message:
        try:
            fail_log_stats = os.stat('fail.log')
            print(f"Fail log size is: {fail_log_stats[6]}")
            if int(fail_log_stats[6]) > (32 * 1000):
                print("Deleting fail log")
                os.remove('fail.log')
        except:
            pass

        try:
            with open('fail.log', 'a') as fail_log:
                for msg in log_messages:
                    fail_log.write(f"{msg}\n")
                fail_log.write("\n")
        except Exception as e:
            print(f"Failed to write log file: {str(e)}")
        await send_sms(caller, failed_message)

async def open_gate(gate_number, caller):
    global outgoing_operation_in_progress

    outgoing_operation_in_progress = True

    try:
        _, _, result = await send('ATH', timeout=5, expect_single_line_response=False)
        await handle_call_ending(result)
        await sleep(500)
        # await call_gate(gate_number, caller)
    except Exception as e:
        print(e)
    finally:
        await sleep(1000)
        outgoing_operation_in_progress = False
        uart_lock.release()
        
async def decline_call():
    try:
        _, _, result = await send('ATH', timeout=5, expect_single_line_response=False)
        await handle_call_ending(result)
    except Exception as e:
        print(e)
    finally:
        await sleep(1000)
        uart_lock.release()
    

async def handle_incoming_call(code, data):
    global incoming_call_in_progress
    global caller
    
    if incoming_call_in_progress:
        return

    device_queue.put_nowait({'event':'incoming-event'})
    
    incoming_call_in_progress = True
    number = data.split(',').pop(0).strip().replace('"', '')
    caller = number
    await uart_lock.acquire()
    device_queue.put_nowait({'event':'incoming-call', 'code': code, 'caller': number})
    await sleep()

async def handle_incoming_sms(_, data):
    global incoming_call_in_progress

    device_queue.put_nowait({'event':'incoming-event'})

    msg_index = data.split(',').pop()
    async with uart_lock:
        incoming_call_in_progress = True
        await send('AT+CMGF=1')
        cmd_status, status, result = await send(f'AT+CMGR={msg_index}', expect_single_line_response=False)
        device_queue.put_nowait({'event':'incoming-sms', 'index': msg_index, 'data': (cmd_status, status, result)})
        incoming_call_in_progress = False

        
async def handle_call_ending(code):
    global caller
    global incoming_call_in_progress

    global callee
    global outgoing_call_in_progress
    
    if incoming_call_in_progress:
        incoming_call_in_progress = False
        event = 'incoming-call-end'
        number = caller
        caller = None
    elif outgoing_call_in_progress:
        outgoing_call_in_progress = False
        event = 'outgoing-call-end'
        number = callee
        callee = None
        
    try:
        device_queue.put_nowait({'event': event, 'code': code, 'number': number})
    except:
        print(code)
    finally:
        await sleep()

async def handle_call_in_progress(code):
    global gate_ring_ok
    global gate_last_urc
    first_ring_event.set()
    
    gate_last_urc = code
    
    if code == 'MO RING' or code == 'MO CONNECTED':
        gate_ring_ok = True

    device_queue.put_nowait({'event': 'outgoing-ringing', 'code': code, 'number': caller})
    await sleep()

async def handle_voltage_related_signals(code):
    if code == 'NORMAL POWER DOWN' or code == 'OVER-VOLTAGE POWER DOWN':
        device_queue.put_nowait({'event': 'exception', 'msg': 'Device shutdown', 'code': code})
        return await sleep()
        
    if 'WARNING' in code:
        debug_queue.put_nowait({'event': 'warning', 'msg': 'Voltage warning', 'code': code})
        return await sleep()

    await sleep()
    
def process_command_result(command, command_result, expect_single_line_response):
    if command_result is not None and len(command_result) and command == command_result[0]:
        command_result = command_result[1:]
        
        
    if command_result and len(command_result):
        status = command_result.pop()
    else:
        status = 'UNKNOWN'
        
    if expect_single_line_response:
        if command_result and len(command_result):
            command_result = command_result.pop()
        else:
            command_result = None
    
    return status, command_result
    

def is_ignored_urc(msg):
    segments = msg.split(':')
    code = segments.pop(0)

    return code in ignore_urc_list
    

async def process_unsolicited(msg):
    segments = msg.split(':')
    code = segments.pop(0)
    
    data = None
    
    if len(segments):
        data = ':'.join(segments)
        
    if code == '+CLIP':
        return await handle_incoming_call(code, data)
    
    if code == '+CMTI':
        return await handle_incoming_sms(code, data)
    
    if code == '+CDRIND':
        return await handle_call_ending(code)
    
    if code == 'MO RING' or code == 'MO CONNECTED' or \
       code == 'BUSY' or code == 'NO CARRIER' or \
       code == 'NO DIALTONE' or code == 'NO ANSWER':
        return await handle_call_in_progress(code)
    
    if 'POWER' in code or 'VOLTAGE' in code:
        return await handle_voltage_related_signals(code)
    
    await sleep()
    
async def send(command, expect_single_line_response = True, timeout = 1, no_wait = False):
    global line_buffer
    global last_command
    
    async with command_lock:
        last_command = command
        cmd_timeout = False
        write_queue.put_nowait(command)
        if no_wait:
            await sleep()
            return None, None, None

        send_status = None
        command_result = None

        try:
            # print('sent', command)
            send_status, command_result = await asyncio.wait_for(read_queue.get(), timeout)
            # print('received', send_status, command_result)
        except asyncio.TimeoutError as e:
            debug_queue.put_nowait({'event': 'error', 'data': {'error': 'Timeout error', 'command': command}})
            await sleep()
            cmd_timeout = True
            
        if cmd_timeout:
            result = line_buffer.copy()
            line_buffer = []
            send_status = 'timeout'
            
        status = None
        result = None

        status, result = process_command_result(command, command_result, expect_single_line_response)

        await sleep()
        if send_status == 'timeout':
            if write_lock.locked():
                write_lock.release()
        return send_status, status, result
        
async def query_state():
    global last_state
    global pin_set
    global pin_timeout_count
    global pin_query_fail_count

    state = last_state.copy()

    async with uart_lock:
        cmd_status, _, result = await send('AT+CPIN?', timeout=2)
        
        if is_busy():
            return
        
        if cmd_status == 'ok':
            state['pin_status'] = result
            pin_timeout_count = 0
            
            if result and result != '+CPIN: READY':
                pin_query_fail_count += 1
                if not pin_set or pin_query_fail_count >= 3:
                    pin_set = True
                    pin_query_fail_count = 0
                    await send('AT')

                    if is_busy():
                        return
    
                    device_queue.put_nowait({'event': 'initializing'})
                    await send('AT+CIURC=0;+CCWA=0;+CLIP=1;+CDRIND=1;+MORING=1;+CMGF=1;+IPR=115200', timeout=5)

                    if is_busy():
                        return

                    _, result = await enter_pin()
                    
                    state['pin_status'] = result
            elif result == '+CPIN: READY':
                device_queue.put_nowait({'event': 'initialized'})
        elif cmd_status == 'timeout':
            pin_timeout_count += 1
            
            if pin_timeout_count > 2:
                device_queue.put_nowait({'event': 'sim-offline'})
            
        if is_busy():
            return

        cmd_status, _, result = await send('AT+COPS?')
        if cmd_status == 'ok':
            state['network'] = result
            
        if is_busy():
            return

        cmd_status, _, result = await send('AT+CSQ')

        if cmd_status == 'ok':
            state['signal'] = result

            try:
                level = int(result.split(':').pop().split(',').pop(0).strip())
            except:
                level = 99
            
            if level < 10:
                state['signal_friendly'] = 'low'
            elif level >= 10 and level < 15:
                state['signal_friendly'] = 'ok'
            elif level >= 15 and level < 20:
                state['signal_friendly'] = 'good'
            elif level >= 20 and level < 32:
                state['signal_friendly'] = 'excellent'
            else:
                state['signal_friendly'] = 'unknown'

        if is_busy():
            return

        cmd_status, _, result = await send('ATI')

        if cmd_status == 'ok':
            state['product'] = result

        if is_busy():
            return
        
        cmd_status, _, result = await send('AT+GSV')

        if cmd_status == 'ok':
            state['product_details'] = result
        
        debug_queue.put_nowait({'event':'state', 'data': state})
        await sleep()

async def enter_pin():
    await send('AT+CPIN=0000', timeout=5)
    await sleep(5000)
    
    cmd_status, _, pin_status = await send('AT+CPIN?')

    if cmd_status == 'ok':
        if pin_status != '+CPIN: READY':
            return 'ERROR', pin_status
        
        return 'OK', pin_status

    return 'ERROR', None

async def do_write():
    while True:
        command = await write_queue.get()
        async with write_lock:
            writer.write(f'{command}\n'.encode())
            await writer.drain()

async def do_read():
    global line_buffer
    read_status = 'ok'
    while True:
        line = await reader.readline()
        try:
            line = line.decode('utf8').strip()
        except:
            line = ''

        if len(line) == 0:
            continue
        
        if debug_mode:
            print(line)
            continue
            

        if is_unsolicited(line):
            if not is_ignored_urc(line):
                read_status = 'interrupted'
                urc_queue.put_nowait(line)
            continue

        # print('L', line)
        line_buffer.append(line)
        
        if line == 'OK' or line == 'ERROR' or '+CME ERROR' in line or '+CMS ERROR' in line:
            await sleep(100)
            read_queue.put_nowait([read_status, line_buffer.copy()])
            line_buffer = []
            read_status = 'ok'
            if write_lock.locked():
                write_lock.release()
            continue
        
async def handle_urc():
    while True:
        urc = await urc_queue.get()
        print('U', urc)

        await process_unsolicited(urc)
        
def toggle_debug_mode(state):
    global debug_mode
    debug_mode = state
    
async def send_at_command(cmd):
    print('Sending command', cmd)
    async with uart_lock:
        await send(cmd, no_wait=True)

    
async def initialize(_device_queue, _debug_queue, _reader, _writer):
    global device_queue
    global debug_queue
    global reader
    global writer

    device_queue = _device_queue
    debug_queue = _debug_queue
    
    reader = _reader
    writer = _writer

    asyncio.create_task(do_write())
    asyncio.create_task(do_read())
    asyncio.create_task(handle_urc())
    
    while True:
        if not debug_mode:
            await query_state()

        await sleep(1000)