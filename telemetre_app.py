#!/usr/bin/env python3
"""
Telemetre Bosch -> Calc (GUI)

Connexion A LA DEMANDE (bouton Connecter) : aucun scan BLE en continu, donc
pas de perturbation des autres appareils Bluetooth (casque, etc.).
Scanne la signature du Bosch (constructeur 678 / service FDE8), se connecte,
affiche les mesures, ecrit le CSV, et pousse dans la cellule Calc selectionnee
si LibreOffice tourne avec un socket.

Dependances : python3 (+tkinter), bleak.  Calc (optionnel) : python3-uno + soffice.
"""
import asyncio, threading, queue, struct, csv, datetime, os
import tkinter as tk
from tkinter import ttk
from bleak import BleakClient, BleakScanner

try:
    import uno
    HAVE_UNO = True
except Exception:
    HAVE_UNO = False

# ----------------------------- CONFIG -----------------------------
CHAR      = "02a6c0d2-0451-4000-b000-fb3210111989"
INIT      = bytes.fromhex("c0550201001a")
MANUF_ID  = 678
CSV_PATH  = os.path.expanduser("~/mesures_telemetre.csv")
UNO_PORT  = 2002
SCAN_SECS = 8.0      # duree d'un scan
MAX_TRIES = 3        # nb de scans avant d'abandonner (puis on attend l'utilisateur)
# ------------------------------------------------------------------

def colref(c, r):
    s = ""; c += 1
    while c > 0:
        c, rem = divmod(c - 1, 26); s = chr(65 + rem) + s
    return f"{s}{r + 1}"

# ----------------------------- UNO / Calc -------------------------
class Calc:
    def __init__(self):
        self.doc = None
    def connect(self):
        lc = uno.getComponentContext()
        res = lc.ServiceManager.createInstanceWithContext(
            "com.sun.star.bridge.UnoUrlResolver", lc)
        ctx = res.resolve(
            f"uno:socket,host=localhost,port={UNO_PORT};urp;StarOffice.ComponentContext")
        smgr = ctx.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        self.doc = desktop.getCurrentComponent()
        return self.doc is not None
    def write(self, value):
        if not HAVE_UNO:
            return None
        try:
            if self.doc is None and not self.connect():
                return None
            ctrl = self.doc.CurrentController
            sel = ctrl.getSelection()
            col = row = sh = None
            try:
                a = sel.CellAddress; sh, col, row = a.Sheet, a.Column, a.Row
            except Exception:
                try:
                    ra = sel.RangeAddress; sh, col, row = ra.Sheet, ra.StartColumn, ra.StartRow
                except Exception:
                    return None
            sheet = self.doc.Sheets.getByIndex(sh)
            sheet.getCellByPosition(col, row).setValue(value)
            try: ctrl.select(sheet.getCellByPosition(col, row + 1))
            except Exception: pass
            return colref(col, row)
        except Exception:
            self.doc = None
            return None

# ----------------------------- BLE (a la demande) -----------------
async def find_bosch(timeout):
    devs = await BleakScanner.discover(timeout=timeout, return_adv=True)
    best, best_rssi = None, -999
    for addr, (d, adv) in devs.items():
        name = (d.name or adv.local_name or "").lower()
        sig = (MANUF_ID in (adv.manufacturer_data or {})) or \
              any("fde8" in u.lower() for u in (adv.service_uuids or [])) or \
              "bosch" in name or "universaldistance" in name or "ud40" in name or "ud 40" in name
        if sig and (adv.rssi or -999) > best_rssi:
            best, best_rssi = addr, (adv.rssi or -999)
    return best

async def ble_session(q, stop):
    """Scan borne -> connexion -> maintien. Pas de scan continu."""
    tries = 0
    while not stop.is_set():
        tries += 1
        q.put(("status", f"Recherche du Bosch (essai {tries}/{MAX_TRIES})..."))
        try:
            addr = await find_bosch(SCAN_SECS)
        except Exception as e:
            addr = None
            q.put(("status", f"Scan KO ({type(e).__name__})"))
        if stop.is_set():
            break
        if not addr:
            if tries >= MAX_TRIES:
                q.put(("status", "Bosch introuvable. Reveille-le et reclique Connecter."))
                break
            await asyncio.sleep(2); continue
        try:
            q.put(("status", f"Connexion a {addr}..."))
            async with BleakClient(addr, timeout=25.0) as client:
                def on_notify(_s, data):
                    data = bytes(data)
                    if len(data) >= 11 and data[0] == 0xC0 and data[1] == 0x55 and data[2] == 0x10:
                        dist = struct.unpack_from("<f", data, 7)[0]
                        if dist == dist:
                            q.put(("measure", dist))
                await client.start_notify(CHAR, on_notify)
                await client.write_gatt_char(CHAR, INIT, response=False)
                q.put(("status", "Connecte - tire avec le Bosch"))
                tries = 0   # succes : on remet le compteur a zero
                while not stop.is_set() and client.is_connected:
                    await asyncio.sleep(0.3)
                try: await client.stop_notify(CHAR)
                except Exception: pass
            if stop.is_set():
                break
            q.put(("status", "Lien perdu - tentative de reconnexion..."))
            await asyncio.sleep(2)
        except Exception as e:
            if tries >= MAX_TRIES:
                q.put(("status", f"Connexion impossible ({type(e).__name__}). Reclique Connecter."))
                break
            await asyncio.sleep(2)
    q.put(("ended", None))

# ----------------------------- GUI -------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Telemetre Bosch")
        self.geometry("440x540")
        self.q = queue.Queue()
        self.stop = threading.Event()
        self.calc = Calc()
        self.count = 0
        self.running = False

        top = ttk.Frame(self, padding=10); top.pack(fill="x")
        self.btn = ttk.Button(top, text="Connecter", command=self.toggle)
        self.btn.pack(side="left")
        self.status = ttk.Label(top, text="Pret. Clique Connecter.", foreground="#555")
        self.status.pack(side="left", padx=10)

        opts = ttk.Frame(self, padding=(10, 0)); opts.pack(fill="x")
        ttk.Label(opts, text="Unite:").pack(side="left")
        self.unit = tk.StringVar(value="mm")
        ttk.Combobox(opts, textvariable=self.unit, values=["mm", "m"],
                     width=5, state="readonly").pack(side="left", padx=4)
        ttk.Label(opts, text="Decimales:").pack(side="left", padx=(10, 0))
        self.dec = tk.IntVar(value=1)
        ttk.Spinbox(opts, from_=0, to=4, textvariable=self.dec, width=4).pack(side="left", padx=4)
        calc_txt = "Calc: detecte" if HAVE_UNO else "Calc: indispo"
        ttk.Label(opts, text=calc_txt, foreground="#888").pack(side="right")

        body = ttk.Frame(self, padding=10); body.pack(fill="both", expand=True)
        sb = ttk.Scrollbar(body, orient="vertical")
        self.list = tk.Listbox(body, font=("monospace", 13), yscrollcommand=sb.set)
        sb.config(command=self.list.yview)
        sb.pack(side="right", fill="y")
        self.list.pack(side="left", fill="both", expand=True)

        bottom = ttk.Frame(self, padding=10); bottom.pack(fill="x")
        ttk.Button(bottom, text="Effacer la liste",
                   command=lambda: self.list.delete(0, "end")).pack(side="left")
        ttk.Label(bottom, text=f"CSV: {CSV_PATH}", foreground="#888").pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self.poll)

    def toggle(self):
        if not self.running:
            self.running = True
            self.stop.clear()
            self.btn.config(text="Deconnecter")
            threading.Thread(target=lambda: asyncio.run(ble_session(self.q, self.stop)),
                             daemon=True).start()
        else:
            self.stop.set()
            self.btn.config(text="Connecter", state="disabled")
            self.status.config(text="Arret en cours...")

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "status":
                    self.status.config(text=val)
                elif kind == "measure":
                    self.handle_measure(val)
                elif kind == "ended":
                    self.running = False
                    self.btn.config(text="Connecter", state="normal")
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def handle_measure(self, dist_m):
        d = self.dec.get()
        out = round(dist_m * 1000, d) if self.unit.get() == "mm" else round(dist_m, d)
        self.count += 1
        cell = self.calc.write(out) if HAVE_UNO else None
        suffix = f"  -> {cell}" if cell else ""
        self.list.insert("end", f"{self.count:3d}.  {out} {self.unit.get()}{suffix}")
        self.list.yview_moveto(1.0)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with open(CSV_PATH, "a", newline="") as f:
            csv.writer(f).writerow([ts, out, self.unit.get()])

    def on_close(self):
        self.stop.set()
        self.destroy()

def main():
    App().mainloop()

if __name__ == "__main__":
    main()
