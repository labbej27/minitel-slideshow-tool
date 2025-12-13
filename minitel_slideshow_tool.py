#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minitel Slideshow Tool
- GUI Tkinter pour convertir des images en .vdt (encodeur intégré)
- Serveur WebSocket local (start/stop/restartables)
- Client WebSocket ↔ port série (keepalive)
- Choix de serveurs prédéfinis + saisie manuelle
- Temps d'affichage paramétrable
"""
from pathlib import Path
from io import BytesIO
from typing import Iterable, Generator, Any, Optional
import warnings, time, threading, asyncio, ssl

import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog as fd
from PIL import Image

import serial, serial.tools.list_ports
import websockets

# SSL workaround
ssl_context = ssl._create_unverified_context()

# ------------------------
# GLOBALS / ETAT
# ------------------------
ser = None
ws = None
running = False

# Slideshow server state
slideshow_server = None            # websockets.server.Serve object
slideshow_server_running = False
server_loop: Optional[asyncio.AbstractEventLoop] = None
server_thread: Optional[threading.Thread] = None

# ------------------------
# SERVERS
# ------------------------
SERVERS = {
    "Localhost (Photos)": "ws://localhost:8765",
    "MiniPAVI": "wss://go.minipavi.fr:8181",
    "Hacker": "ws://mntl.joher.com:2018",
    "Annuaire": "ws://3611.re/ws",
    "3615": "ws://3615co.de/ws",
    "Retrocampus": "wss://bbs.retrocampus.com:8051",
    "LABBEJ27": "wss://minitel.labbej.fr:8182",
    "Saisie manuelle…": ""
}

# ------------------------
# UTIL: LOG
# ------------------------
def log(text: str, log_widget: scrolledtext.ScrolledText):
    ts = time.strftime("%H:%M:%S")
    log_widget.configure(state="normal")
    log_widget.insert(tk.END, f"[{ts}] {text}\n")
    log_widget.see(tk.END)
    log_widget.configure(state="disabled")

# ------------------------
# ENCODE (essentiel, allégé mais compatible pic2jpeg2vdt)
# ------------------------
def bytescat(*data: 'Iterable[bytes | int] | int') -> bytes:
    r = bytearray()
    for e in data:
        if isinstance(e, (bytes, bytearray)):
            r.extend(e)
        elif isinstance(e, int):
            r.append(e)
        else:
            r.extend(bytescat(*e))
    return bytes(r)

SCREEN_WIDTH = 320
SCREEN_HEIGHT = 240

# Attributes (short names)
PSA = bytescat(0x20); PDA = bytescat(0x21); SPA = bytescat(0x22); SSA = bytescat(0x23); SCA = bytescat(0x24); TCA = bytescat(0x25)
RTD = bytescat(PSA, 0x30)
PDA_LOC = bytescat(PDA, 0x32); PDA_PAS = bytescat(PDA, 0x33); PDA_PPL = bytescat(PDA, 0x34); PDA_CPA = bytescat(PDA, 0x35)
SCA_JPG = bytescat(SCA, 0x30); TME = bytescat(TCA, 0x30)
PM = 0x23; PI = 0x40

QTABLE_0 = [16,11,10,16,24,40,51,61,12,12,14,19,26,58,60,55,14,13,16,24,40,57,69,56,14,17,22,29,51,87,80,62,18,22,37,56,68,109,103,77,24,35,55,64,81,104,113,92,49,64,78,87,103,121,120,101,72,92,95,98,112,100,103,99]
QTABLE_1 = [17,18,24,47,99,99,99,99,18,21,26,66,99,99,99,99,24,26,56,99,99,99,99,99,47,66,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99,99]

def iter_jpeg_sections(data: bytes) -> 'Generator[tuple[int,int], None, None]':
    pos = 0
    if data[pos:pos+2] != b'\xFF\xD8': raise ValueError("Invalid JPEG")
    pos += 2
    while data[pos] == 0xFF and data[pos+1] != 0xDA:
        length = (data[pos+2] << 8) | data[pos+3]
        yield (pos, pos+length+2)
        pos += length + 2
    if data[pos:pos+2] != b'\xFF\xDA' or data[-2:] != b'\xFF\xD9':
        raise ValueError("Invalid JPEG")
    yield (pos, len(data))

def trim_jpeg(data: bytes) -> bytes:
    res = bytearray(b'\xFF\xD8')
    for b,e in iter_jpeg_sections(data):
        if data[b:b+2] in (b'\xFF\xDA', b'\xFF\xC0', b'\xFF\xDB'):
            res.extend(data[b:e])
    return bytes(res)

def has_qtables(data: bytes) -> bool:
    return any(data[b:b+2] == b'\xFF\xDB' for b,e in iter_jpeg_sections(data))

def encode_length(value: int) -> bytes:
    out = bytearray()
    first = True
    while value != 0:
        tmp = value & 31
        tmp |= (1 << 6)
        if not first:
            tmp |= (1 << 5)
        else:
            first = False
        value >>= 5
        out.append(tmp)
    out.append(0xFF)
    out.reverse()
    return bytes(out)

def encode_integer(number: int, raw: bool = False) -> bytes:
    # minimal integer encoding used by header
    nbits = 7
    while not -(1 << (nbits-1)) <= number < (1 << (nbits-1)):
        nbits += 7
    if number < 0:
        number += (1 << nbits)
    data = bytearray()
    if not raw:
        data.append(0x40)
        # length in bytes (nbits//7)
        data.extend(bytes([nbits//7]))
    for i in reversed(range(0, nbits, 7)):
        data.append((number >> i) & 0x7F)
    return bytes(data)

def encode_normalized(value: float) -> bytes:
    nbytes = 4
    if not (-1 <= value <= 1): raise ValueError
    v = round(value * (1 << ((7*nbytes)-2)))
    if v < 0:
        v = v + (1 << (7*nbytes)) - (1 << ((7*nbytes)-2))
    return bytescat(0x42, nbytes, [(v >> (7*i)) & 0x7F for i in reversed(range(nbytes))])

def encode_boolean(v: bool) -> bytes:
    return bytescat(0x45, 0x01, 0x01 if v else 0x00)

def resize_image(im: Image.Image) -> Image.Image:
    ratio = min(SCREEN_WIDTH / im.width, SCREEN_HEIGHT / im.height, 1)
    w = round(im.width * ratio); w = ((w + 4)//8)*8
    h = round(im.height * ratio); h = ((h + 5)//10)*10
    if im.width == w and im.height == h: return im
    return im.resize((w,h), Image.LANCZOS)

def encode_header(x:int,y:int,width:int,height:int, *, clear:bool=True, translation:bool=False, reset:bool=True, quantization:bool=False) -> bytes:
    h = bytearray()
    if reset: h.extend(bytescat(RTD, encode_boolean(True)))
    h.extend(bytescat(PDA_LOC, encode_normalized(x/SCREEN_WIDTH), encode_normalized((SCREEN_HEIGHT-height-y)/SCREEN_HEIGHT*0.75)))
    h.extend(bytescat(PDA_PAS, encode_normalized(width/SCREEN_WIDTH), encode_normalized(height/SCREEN_HEIGHT*0.75)))
    h.extend(bytescat(PDA_PPL, encode_integer(0), encode_integer(0), encode_normalized(0), encode_normalized(height/SCREEN_HEIGHT*0.75)))
    if clear: h.extend(bytescat(PDA_CPA, encode_boolean(clear)))
    if quantization: h.extend(bytescat(ETM:=bytescat(SCA,0x31), bytescat(0x44,0x01,1), encode_integer(0x7F), bytescat(0x44,0x01,0x03)))
    if translation: h.extend(bytescat(TME, bytescat(0x44,0x01,0x02)))
    return bytes(h)

def export_image(im: Image.Image, *, subsampling: str="4:2:2", quality: Optional[int]=None) -> bytes:
    if im.mode not in ("YCbCr","RGB","L"): im = im.convert("YCbCr")
    kwargs = {"subsampling":subsampling,"optimize":False,"progressive":False,"keep_rgb":False,"restart_marker_blocks":False,"restart_marker_rows":False}
    if quality is None:
        kwargs["qtables"]=[QTABLE_0,QTABLE_1]; kwargs["streamtype"]=2
    else:
        kwargs["quality"]=quality; kwargs["streamtype"]=0
    buf = BytesIO(); im.save(buf,"JPEG",**kwargs)
    return trim_jpeg(buf.getvalue())

def split_chunks(data: bytes, chunk_size: int) -> 'Generator[tuple[bytes,bool], None, None]':
    if chunk_size <= 0 or not data:
        yield (data, True); return
    for pos in range(0, len(data), chunk_size):
        chunk = data[pos:pos+chunk_size]; final = (pos+len(chunk) >= len(data))
        yield (chunk, final)

def translate_data(data: bytes) -> bytes:
    res = bytearray(); pos = 0
    while pos < len(data):
        chunk = data[pos:pos+3]; b0 = (1<<6)
        for idx, bt in enumerate(chunk): b0 |= ((bt>>6) << (4 - (idx<<1)))
        res.append(b0); res.extend((1<<6)|(bt&0x3F) for bt in chunk); pos+=3
    return bytes(res)

def encode_image(header: bytes, image: bytes, chunk_size: int=0x100, *, translation: bool=False) -> list[bytes]:
    out = []
    for chunk, final in split_chunks(header, chunk_size-1):
        code = 0x51 if final else 0x50
        out.append(bytescat(0x1B,0x70,PM,PI,encode_length(len(chunk)+1), code, chunk))
    if translation:
        chunk_size = (((chunk_size-1)*3)//4) + 1
    for chunk, final in split_chunks(image, chunk_size):
        if translation: chunk = translate_data(chunk)
        code = 0x53 if final else 0x52
        out.append(bytescat(0x1B,0x70,PM,PI,encode_length(len(chunk)+1), code, chunk))
    return out

# ------------------------
# Conversion (thread-safe caller)
# ------------------------
def convert_images(input_folder: str, output_folder: str, log_widget: scrolledtext.ScrolledText, preview: bool=False):
    inp = Path(input_folder or ""); out = Path(output_folder or "")
    if not inp.exists() or not inp.is_dir():
        log("Dossier d'entrée introuvable.", log_widget); return
    out.mkdir(parents=True, exist_ok=True)
    imgs = sorted([p for p in inp.iterdir() if p.suffix.lower() in (".jpg",".jpeg",".png",".bmp",".webp",".tif",".tiff")])
    if not imgs:
        log("Aucune image trouvée.", log_widget); return
    log(f"Conversion {len(imgs)} images…", log_widget)
    for p in imgs:
        try:
            im = Image.open(p)
            im = resize_image(im)
            jpeg = export_image(im, quality=78)
            header = encode_header(0,0,im.width,im.height, clear=True, translation=False, reset=True, quantization=has_qtables(jpeg))
            chunks = encode_image(header, jpeg, chunk_size=0x100, translation=False)
            outp = out / (p.stem + ".vdt")
            with open(outp, "wb") as f:
                for c in chunks: f.write(c)
            log(f"Converti: {p.name} -> {outp.name}", log_widget)
            if preview:
                # small hex summary in log (first 64 bytes)
                sample = (outp.read_bytes()[:64]).hex()
                log(f"Preview hex (first 64 bytes): {sample}", log_widget)
        except Exception as e:
            log(f"Erreur conversion {p.name}: {e}", log_widget)
    log("Conversion terminée.", log_widget)

# ------------------------
# Slideshow server (architecture STANDARD - thread per server loop)
# ------------------------
async def slideshow_handler(ws_conn, path, vdt_files, delay):
    INIT_SEQUENCE = b"\x1B@" + b"\x1B:" + b"\x1B[25l"
    CLEAR = b"\x1B[2J\x1B[H"  # Clear + home

    await ws_conn.send(INIT_SEQUENCE)
    await asyncio.sleep(0.1)

    try:
        while True:
            for v in vdt_files:
                await ws_conn.send(CLEAR)
                await asyncio.sleep(0.02)

                data = v.read_bytes()
                await ws_conn.send(data)

                await asyncio.sleep(delay)

    except websockets.exceptions.ConnectionClosed:
        return

async def start_slideshow_server(host: str, port: int, vdt_folder: str, delay: float, log_widget: scrolledtext.ScrolledText):
    global slideshow_server, slideshow_server_running
    slideshow_server_running = True
    vdt_files = sorted(Path(vdt_folder).glob("*.vdt"))
    if not vdt_files:
        log("Aucun .vdt dans dossier.", log_widget); return
    slideshow_server = await websockets.serve(lambda ws, path=None: slideshow_handler(ws, path, vdt_files, delay), host, port)
    log(f"Serveur slideshow en écoute sur {host}:{port}", log_widget)
    try:
        while slideshow_server_running:
            await asyncio.sleep(0.1)
    finally:
        slideshow_server.close()
        await slideshow_server.wait_closed()
        log("Serveur slideshow fermé (loop interne).", log_widget)

def launch_slideshow_server(host: str, port: int, vdt_folder: str, delay: float, log_widget: scrolledtext.ScrolledText):
    global server_loop, server_thread, slideshow_server_running
    if slideshow_server_running:
        log("Slideshow server déjà démarré.", log_widget); return
    if not Path(vdt_folder).exists():
        log("Dossier VDT introuvable.", log_widget); return
    log(f"Démarrage slideshow server {host}:{port} (delay={delay}s)…", log_widget)
    server_loop = asyncio.new_event_loop()
    def _runner():
        try:
            server_loop.run_until_complete(start_slideshow_server(host, port, vdt_folder, delay, log_widget))
        except Exception as e:
            # loop stopped or error
            log(f"Serveur loop terminé: {e}", log_widget)
        finally:
            # ensure loop closed
            try: server_loop.run_until_complete(server_loop.shutdown_asyncgens())
            except: pass
            server_loop.close()
    server_thread = threading.Thread(target=_runner, daemon=True)
    server_thread.start()

def stop_slideshow_server(log_widget: scrolledtext.ScrolledText):
    global slideshow_server_running, server_loop, server_thread, slideshow_server
    if not slideshow_server_running:
        log("Aucun slideshow server en cours.", log_widget); return
    log("Arrêt du slideshow server demandé…", log_widget)
    slideshow_server_running = False
    if server_loop and slideshow_server:
        # close server safely in its loop
        async def _close_and_stop():
            try:
                slideshow_server.close()
                await slideshow_server.wait_closed()
            except Exception:
                pass
            finally:
                server_loop.stop()
        try:
            asyncio.run_coroutine_threadsafe(_close_and_stop(), server_loop)
        except Exception:
            pass
    # wait a short time for thread to finish
    if server_thread:
        server_thread.join(timeout=2)
    slideshow_server = None
    server_loop = None
    log("Slideshow server arrêté (commande émise).", log_widget)

# ------------------------
# send_vdt helper
# ------------------------
async def send_vdt(ws_conn, data: bytes):
    lines = data.split(b"\n")
    chunk = bytearray(); count = 0
    for line in lines:
        chunk.extend(line + b"\n"); count += 1
        if count >= 10:
            await ws_conn.send(chunk); await asyncio.sleep(0.06); chunk.clear(); count = 0
    if chunk:
        await ws_conn.send(chunk)

# ------------------------
# Client WebSocket <-> Serial (thread + loop)
# ------------------------
async def websocket_task(url, tty, speed, parity, databits, stopbits, status_label, log_widget):
    global ser, ws, running
    STOPBITS = {"1": serial.STOPBITS_ONE, "1.5": serial.STOPBITS_ONE_POINT_FIVE, "2": serial.STOPBITS_TWO}
    try:
        log(f"Ouverture port série {tty} @ {speed}…", log_widget)
        ser = serial.Serial(tty, int(speed), parity=parity, bytesize=int(databits), stopbits=STOPBITS[stopbits], timeout=1)
    except Exception as e:
        log(f"Erreur ouverture série: {e}", log_widget)
        status_label.config(text="Erreur port série")
        return
    try:
        log(f"Connexion WS -> {url}…", log_widget)
        if url.startswith("wss://"):
            ws = await websockets.connect(url, ssl=ssl_context)
        else:
            ws = await websockets.connect(url)
        status_label.config(text="Connecté")
        log("WS connecté.", log_widget)
        # small greeting
        try:
            ser.write(b"\x07\x0c\x1f\x40\x41connexion\x0a")
            ser.write(b"\x1b\x3b\x60\x58\x52")
        except Exception:
            pass

        async def w2m():
            while running:
                try:
                    data = await ws.recv()
                    if isinstance(data, bytes):
                        ser.write(data)
                        log(f"[WS→Minitel] {len(data)} bytes", log_widget)
                    else:
                        ser.write(data.encode("latin1","replace"))
                        log(f"[WS→Minitel] text", log_widget)
                except Exception:
                    break

        async def m2w():
            while running:
                try:
                    if ser.in_waiting > 0:
                        d = ser.read(ser.in_waiting)
                        await ws.send(d.decode("latin1","replace"))
                        log(f"[Minitel→WS] {len(d)} bytes", log_widget)
                    else:
                        await asyncio.sleep(0.05)
                except Exception:
                    break

        async def keepalive():
            while running:
                try:
                    await ws.ping()
                except Exception:
                    break
                await asyncio.sleep(20)

        await asyncio.gather(w2m(), m2w(), keepalive())
    except Exception as e:
        log(f"Erreur WS/IO: {e}", log_widget)
        status_label.config(text="Erreur")
    finally:
        running = False
        log("Fermeture client WS/Serial…", log_widget)
        try:
            if ws:
                await ws.close()
        except: pass
        try:
            if ser:
                ser.close()
        except: pass
        status_label.config(text="Déconnecté")
        log("Client arrêté.", log_widget)

def start_async(url, tty, speed, parity, databits, stopbits, status_label, log_widget):
    global running
    if running:
        log("Déjà connecté.", log_widget); return
    running = True
    loop = asyncio.new_event_loop()
    def _run():
        try:
            loop.run_until_complete(websocket_task(url, tty, speed, parity, databits, stopbits, status_label, log_widget))
        except Exception as e:
            log(f"Client loop ended: {e}", log_widget)
        finally:
            try: loop.run_until_complete(loop.shutdown_asyncgens())
            except: pass
            loop.close()
    threading.Thread(target=_run, daemon=True).start()

def stop_connection(status_label, log_widget):
    global running
    running = False
    status_label.config(text="Déconnecté")
    log("Arrêt demandé (client série/ws).", log_widget)

# ------------------------
# UTIL: refresh ports
# ------------------------
def update_ports(combo):
    current = set(combo["values"])
    detected = {p.device for p in serial.tools.list_ports.comports()}
    if detected != current:
        combo["values"] = list(detected)
        if detected:
            combo.set(list(detected)[0])

# ------------------------
# GUI (minimal, single-file)
# ------------------------
def build_gui():
    root = tk.Tk(); root.title("Minitel Slideshow Tool — All-in-one (standard)")
    padx = 6; pady = 4

    tk.Label(root, text="Serveur").grid(row=0, column=0, sticky="w", padx=padx, pady=pady)
    server_combo = ttk.Combobox(root, values=list(SERVERS.keys()), width=40); server_combo.set("Localhost (Photos)"); server_combo.grid(row=0,column=1,sticky="w",padx=padx,pady=pady)
    tk.Label(root, text="Adresse WebSocket").grid(row=1, column=0, sticky="w", padx=padx, pady=pady)
    url_entry = tk.Entry(root, width=44); url_entry.insert(0, SERVERS["Localhost (Photos)"]); url_entry.grid(row=1,column=1,sticky="w",padx=padx,pady=pady)
    def update_manual(e=None):
        choice = server_combo.get(); url_entry.delete(0,tk.END); url_entry.insert(0, SERVERS.get(choice,"") or "")
    server_combo.bind("<<ComboboxSelected>>", update_manual)

    tk.Label(root, text="Port série").grid(row=2,column=0,sticky="w",padx=padx,pady=pady)
    ports = [p.device for p in serial.tools.list_ports.comports()]
    port_combo = ttk.Combobox(root, values=ports, width=20); port_combo.grid(row=2,column=1,sticky="w",padx=padx,pady=pady)
    if ports: port_combo.set(ports[0])

    tk.Label(root, text="Vitesse").grid(row=3,column=0,sticky="w",padx=padx,pady=pady)
    speed_combo = ttk.Combobox(root, values=["1200","4800","9600","19200"], width=20); speed_combo.set("9600"); speed_combo.grid(row=3,column=1,sticky="w",padx=padx,pady=pady)

    tk.Label(root, text="Parité").grid(row=4,column=0,sticky="w",padx=padx,pady=pady)
    parity_map = {"Even (pair)": serial.PARITY_EVEN, "Odd (impair)": serial.PARITY_ODD, "None": serial.PARITY_NONE, "Mark": serial.PARITY_MARK, "Space": serial.PARITY_SPACE}
    parity_combo = ttk.Combobox(root, values=list(parity_map.keys()), width=20); parity_combo.set("None"); parity_combo.grid(row=4,column=1,sticky="w",padx=padx,pady=pady)

    tk.Label(root, text="Bits").grid(row=5,column=0,sticky="w",padx=padx,pady=pady)
    databits_combo = ttk.Combobox(root, values=["7","8"], width=20); databits_combo.set("8"); databits_combo.grid(row=5,column=1,sticky="w",padx=padx,pady=pady)

    tk.Label(root, text="Stopbits").grid(row=6,column=0,sticky="w",padx=padx,pady=pady)
    stopbits_combo = ttk.Combobox(root, values=["1","1.5","2"], width=20); stopbits_combo.set("1"); stopbits_combo.grid(row=6,column=1,sticky="w",padx=padx,pady=pady)

    status_label = tk.Label(root, text="En attente…"); status_label.grid(row=7,column=0,columnspan=2,sticky="w",padx=padx,pady=pady)
    log_widget = scrolledtext.ScrolledText(root, width=80, height=12, state="disabled"); log_widget.grid(row=8,column=0,columnspan=2,padx=padx,pady=pady)

    tk.Button(root, text="Connecter", command=lambda: start_async(url_entry.get(), port_combo.get(), speed_combo.get(), parity_map[parity_combo.get()], databits_combo.get(), stopbits_combo.get(), status_label, log_widget)).grid(row=9,column=0,sticky="ew",padx=padx,pady=pady)
    tk.Button(root, text="Déconnecter", command=lambda: stop_connection(status_label, log_widget)).grid(row=9,column=1,sticky="ew",padx=padx,pady=pady)

    # Slideshow / Conversion
    frame = tk.LabelFrame(root, text="Slideshow / Conversion"); frame.grid(row=10,column=0,columnspan=2,sticky="we",padx=padx,pady=pady)
    tk.Label(frame, text="Input Images Folder").grid(row=0,column=0,sticky="w",padx=padx,pady=pady)
    input_entry = tk.Entry(frame, width=50); input_entry.grid(row=0,column=1,padx=padx,pady=pady)
    tk.Button(frame, text="Select", command=lambda: select_folder(input_entry)).grid(row=0,column=2,padx=padx,pady=pady)
    tk.Label(frame, text="Output VDT Folder").grid(row=1,column=0,sticky="w",padx=padx,pady=pady)
    output_entry = tk.Entry(frame, width=50); output_entry.grid(row=1,column=1,padx=padx,pady=pady)
    tk.Button(frame, text="Select", command=lambda: select_folder(output_entry)).grid(row=1,column=2,padx=padx,pady=pady)
    tk.Button(frame, text="Convert Images", command=lambda: threading.Thread(target=convert_images, args=(input_entry.get(), output_entry.get(), log_widget, True), daemon=True).start()).grid(row=2,column=0,columnspan=3,sticky="we",padx=padx,pady=pady)
    tk.Label(frame, text="Temps par image (s)").grid(row=3,column=0,sticky="w",padx=padx,pady=pady)
    delay_entry = tk.Entry(frame, width=10); delay_entry.insert(0,"3"); delay_entry.grid(row=3,column=1,sticky="w",padx=padx,pady=pady)
    tk.Button(frame, text="Start Slideshow Server", command=lambda: launch_slideshow_server("0.0.0.0", 8765, output_entry.get(), max(0.1, float(delay_entry.get() or 3.0)), log_widget)).grid(row=4,column=0,columnspan=3,sticky="we",padx=padx,pady=pady)
    tk.Button(frame, text="Stop Slideshow Server", command=lambda: stop_slideshow_server(log_widget)).grid(row=5,column=0,columnspan=3,sticky="we",padx=padx,pady=pady)

    # refresh ports
    def refresh_ports():
        update_ports(port_combo); root.after(1000, refresh_ports)
    refresh_ports()
    root.mainloop()

# ------------------------
# simple helpers
# ------------------------
def select_folder(entry):
    d = fd.askdirectory()
    if d:
        entry.delete(0,tk.END); entry.insert(0,d)

# ------------------------
# ENTRY POINT
# ------------------------
if __name__ == "__main__":
    build_gui()
