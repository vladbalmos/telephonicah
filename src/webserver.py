import time
import json
import uasyncio as asyncio
import network
import os
    
server_initialized = False
command_queue = None
state = None
start_ticks = time.ticks_ms()

wlan = None
ssid = None
ip = None
port = None
wifi_connected_msg_logged = False

wifi_status_codes = {
    network.STAT_IDLE: 'idle',
    network.STAT_CONNECTING: 'connecting',
    network.STAT_WRONG_PASSWORD: 'wrong-password',
    network.STAT_NO_AP_FOUND: 'no-access-point',
    network.STAT_CONNECT_FAIL: 'unknown-error',
    network.STAT_GOT_IP: 'connected'
}

def tstamp():
    now = time.ticks_ms()
    return time.ticks_diff(now, start_ticks) / 1000

class LogsQueue():

    def __init__(self, size=16):
        self.logs = []
        self._max_size = size
        
    def put_nowait(self, item):
        if not server_initialized:
            return

        if len(self.logs) == self._max_size:
            self.logs.pop(0)
            
        self.logs.append((tstamp(), item))
        
logs_queue = LogsQueue()

def url_decode(encoded_str):
    decoded_str = ''
    i = 0
    while i < len(encoded_str):
        if encoded_str[i] == '%' and i + 2 < len(encoded_str):
            hex_value = encoded_str[i + 1:i + 3]
            decoded_char = chr(int(hex_value, 16))
            decoded_str += decoded_char
            i += 3
        elif encoded_str[i] == '+':
            decoded_str += ' '
            i += 1
        else:
            decoded_str += encoded_str[i]
            i += 1
    return decoded_str

async def sleep(ms = 1000):
    return await asyncio.sleep_ms(ms)

async def wifi_connect(_ssid, ssid_password):
    global ssid
    global ip
    global wlan
    global wifi_connected_msg_logged
    
    ssid = _ssid
    
    if not wlan:
        command_queue.put_nowait({'do': 'notif-wifi-connecting'})
        wlan = network.WLAN(network.STA_IF)
        print('Creating WLAN')

    if not wlan.active():
        print('Setting WLAN active')
        wlan.active(True)
        
    if wlan.isconnected():
        if wifi_connected_msg_logged is False:
            config = wlan.ifconfig()
            ip = config[0]
            command_queue.put_nowait({'do': 'handle-wifi-status', 'payload': {'status': True, 'ip': ip, 'port': port, 'ssid': ssid, 'password': ssid_password}})
            print("WIFI connected")
            wifi_connected_msg_logged = True
        return
    
    print(f'Connecting to WIFI {ssid} using {ssid_password}')
    wlan.connect(ssid, ssid_password)
    
    max_wait = 10
    
    while max_wait > 0:
        status = wlan.status()
        print(f"Wifi status is: {status}")
        if status >= 3:
            break
        max_wait -= 1
        print('Waiting for connection')
        await sleep(1000)
        

    status = wlan.status()
    try :
        str_status = wifi_status_codes[status]
    except KeyError:
        str_status = 'unknown-status'
        
    if status != network.STAT_GOT_IP:
        print(f'WIFI Status is {status}/{str_status}')
        command_queue.put_nowait({'do': 'handle-wifi-status', 'payload': {'status': False, 'code': status}})
        return
    
    config = wlan.ifconfig()
    ip = config[0]
    command_queue.put_nowait({'do': 'handle-wifi-status', 'payload': {'status': True, 'ip': ip, 'port': port, 'ssid': ssid, 'password': ssid_password}})
    print("WIFI connected")

def parse_params(str_params):
    params = str_params.split('&')
    
    query_params = []

    for p in params:
        if not len(p):
            continue

        p_segments = p.split('=')
        name = p_segments.pop(0)
        if not name:
            continue
        
        value = '='.join(p_segments)
        query_params.append((name, url_decode(value)))
        
    return query_params

def parse_uri(uri):
    if '?' not in uri:
        return uri, []
    
    segments = uri.split('?')
    
    uri = segments.pop(0)
    params = '?'.join(segments)
    query_params = parse_params(params)
        
    return uri, query_params

def parse_form_data(str_form):
    decoded_form_data = parse_params(url_decode(str_form))
    
    data = {}
    for item in decoded_form_data:
        key, value = item
        value = url_decode(value.strip())
        if '[]' in key:
            key = key[0:-2]
            
            if key not in data:
                data[key] = []
        
            data[key].append(value)
        else:
            data[key] = value
            
    return data
                
    

async def serve_index(method, _headers, _query, _body):
    if method == 'post':
        return '404', 'Not found', [], ''
    
    def stream_response(writer):
        with open('index.html', 'r') as file:
            allowed_callers = []
            for phone, name in state['allowed_callers'].items():
                item = f'<li id="{phone}">{phone} - {name} <input type="hidden" name="name[]" value="{name}"><input type="hidden" name="phone[]" value="{phone}"> <a href="#" rel="{phone}" class="delete-icon" title="Șterge"></a></li>\n'
                allowed_callers.append(item)

            while True:
                line = file.readline()
                if not line:
                    break
                
                if line.strip() == '{allowed_callers}':
                    for caller in allowed_callers:
                        writer.write(caller)
                    continue
                        
                if line.strip() == '{logs}':
                    for (tstamp, item) in logs_queue.logs:
                        writer.write(f'{tstamp} - {item}\n')
                    continue
                
                if '{current_owner}' in line:
                    line = line.replace('{current_owner}', state['owner_number'])

                if '{gate}' in line:
                    line = line.replace('{gate}', state['gate_number'])
                    
                writer.write(line.encode('utf8'))
            
    return '200', 'OK', [], stream_response

async def serve_update(method, _, query, body):
    if method != 'post':
        return '404', 'Not found', [], ''
    
    def stream_logs(writer):
        try:
            with open('fail.log', 'r') as fail_log:
                while True:
                    line = fail_log.readline()
                    if not line:
                        break
                    
                    writer.write(line.encode('utf8'))
        except:
            pass
        
    form_data = {}
    if body:
        form_data = parse_form_data(body.decode())
    
    if ('allowed', '1') in query:
        if not 'name' in form_data or not 'phone' in form_data:
            return '500', 'Internal Server Error', [], 'Missing names or phone numbers!'
        
        if len(form_data['name']) != len(form_data['phone']):
            return '500', 'Internal Server Error', [], 'Mismatch names and phone numbers length!'
        
        if not len(form_data['name']):
            return '500', 'Internal Server Error', [], 'Team members must not be empty!'
        
        updates = []
        for i in range(0, len(form_data['name'])):
            name = form_data['name'][i]
            phone = form_data['phone'][i]
            updates.append((name, phone))
            
        command_queue.put_nowait({'do': 'update-allowed-callers', 'payload': updates})
    elif ('owner', '1') in query:
        if not 'owner' in form_data or not len(form_data['owner']):
            return '500', 'Internal Server Error', [], 'Missing owner number!'
        
        command_queue.put_nowait({'do': 'update-owner-number', 'payload': form_data['owner']})
    elif ('gate', '1') in query:
        if not 'gate' in form_data or not len(form_data['gate']):
            return '500', 'Internal Server Error', [], 'Missing gate number!'

        command_queue.put_nowait({'do': 'update-gate-number', 'payload': form_data['gate']})
    elif ('check:credit', '1') in query:
        command_queue.put_nowait({'do': 'check-credit'})
    elif ('download:logs', '1') in query:
        try:
            fail_log_stat = os.stat('fail.log')
            file_size = fail_log_stat[6]
            response_headers = ['Content-type: text/plain\r\n', f'Content-length: {file_size}\r\n']
            response_headers.append('Content-disposition: attachment; filename="fail.log"\r\n')
            return '200', 'OK', response_headers, stream_logs
        except:
            return '404', 'Not found', [], ''
    else:
        return '403', 'Forbidden', [], 'Unauthorized update!'
    
    # wait for the list to be updated
    await sleep(250)
    return '302', 'Found', ['Location: /'], ''

async def serve(method, headers, uri, query, body):
    action = None
    
    if uri == '/':
        action = serve_index
    elif uri == '/update':
        action = serve_update
        
    if not action:
        return 404, 'Not found', [], ''
    
    return await action(method, headers, query, body)

async def serve_client(reader, writer):
    try:
        request = await reader.readline()
    except:
        return
    
    try:
        request = request.decode('utf8').strip()
    except:
        request = ''
        
    if not request:
        writer.close()
        print('Client disconnected')
        return await writer.wait_closed()
        
        
    headers = []
    
    while True:
        header = await reader.readline()
        if not len(header):
            break

        try:
            header = header.decode('utf8').strip()
        except:
            header = ''
            continue
        
        if not len(header):
            break
        
        headers.append(header)
        
    read_body = False
    try:
        for h in headers:
            key, value = h.split(': ', 1)
            if key.lower() == 'content-length':
                value = int(value)
                read_body = value
    except Exception as e:
        writer.write(b'HTTP/1.0 500 Internal Server Error\r\nContent-type: text/html\r\n\r\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return print('Caught exception while parsing headers. Client disconnected', e)
    
    segments = request.split(' ')
    method = None
    uri = None
    body = None

    try:
        method = segments.pop(0).lower()
        uri = segments.pop(0).lower()
    except Exception as e:
        writer.write(b'HTTP/1.0 500 Internal Server Error\r\nContent-type: text/html\r\n\r\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return print('Caught exception while parsing request. Client disconnected', e)
   
    uri, query = parse_uri(uri)
    
    if read_body:
        body = await reader.readexactly(read_body)
        
    try:
        status, text, headers, response = await serve(method, headers, uri, query, body)
    except Exception as e:
        writer.write(b'HTTP/1.0 500 Internal Server Error\r\nContent-type: text/html\r\n\r\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        return print('Caught exception while service request. Client disconnected', e)

    http_status = f'HTTP/1.0 {status} {text}\r\n'
    if not len(headers):
        headers = ['Content-type: text/html\r\n']
        
    writer.write(http_status.encode('ascii'))
    for h in headers:
        writer.write(h.encode('ascii'))
        
    writer.write(b'\r\n')
    
    if callable(response):
        response(writer)
    elif len(response):
        writer.write(response.encode('utf8'))
        
    await writer.drain()
    writer.close()
    await writer.wait_closed()
    print(tstamp(), 'Served request', uri)
    
def set_new_state(_state):
    global state
    state = _state
    
def status():
    if not wlan or not wlan.isconnected():
        return False, {}
        
    return True, {'ip': ip, 'port': port}


async def initialize(_command_queue, _state, ssid, ssid_password, _port=8080):
    global server_initialized
    global command_queue
    global state
    global port
    
    command_queue = _command_queue
    state = _state
    port = _port

    await wifi_connect(ssid, ssid_password)
    asyncio.create_task(asyncio.start_server(serve_client, '0.0.0.0', port))
    server_initialized = True
    
    while True:
        # Check wifi status every second and try to reconnect in case of network issues
        await wifi_connect(ssid, ssid_password)
        await sleep()
    
