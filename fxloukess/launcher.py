import tkinter as tk
import subprocess
import threading
import os
import signal
import time
import webbrowser

process = None
running = False
auto_restart = True

venv_python = os.path.join(os.getcwd(), "venv", "Scripts", "python.exe")

# ---------- SERVER CONTROL ----------

def start_server():
    global process, running

    if process is not None:
        log(">>> already running\n")
        return

    try:
        process = subprocess.Popen(
            [venv_python, "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

        running = True
        update_status()

        threading.Thread(target=read_logs, daemon=True).start()
        threading.Thread(target=watch_process, daemon=True).start()

        log(">>> server started\n")

    except Exception as e:
        log(f">>> ERROR: {e}\n")


def stop_server():
    global process, running

    if process is None:
        log(">>> nothing to stop\n")
        return

    try:
        process.send_signal(signal.CTRL_BREAK_EVENT)
    except:
        pass

    try:
        process.kill()
    except:
        pass

    process = None
    running = False
    update_status()
    log(">>> server stopped\n")


def watch_process():
    global process, running

    process.wait()  # wait until it dies

    if running:  # means it crashed, not manual stop
        log(">>> crashed\n")
        running = False
        update_status()

        if auto_restart:
            log(">>> restarting...\n")
            time.sleep(2)
            start_server()


def read_logs():
    global process

    try:
        for line in process.stdout:
            log(line)
    except:
        pass


# ---------- UI ACTIONS ----------

def open_host():
    webbrowser.open("http://localhost:8000")


def toggle_restart():
    global auto_restart
    auto_restart = not auto_restart
    restart_btn.config(
        text=f"Auto Restart: {'ON' if auto_restart else 'OFF'}"
    )


def update_status():
    if running:
        status_label.config(text="● RUNNING", fg="#00ff88")
    else:
        status_label.config(text="● STOPPED", fg="#ff4444")


def log(text):
    log_box.insert(tk.END, text)
    log_box.see(tk.END)


# ---------- UI ----------

root = tk.Tk()
root.title("fxloukess control")
root.geometry("800x450")
root.configure(bg="#1e1e1e")

# left panel
side = tk.Frame(root, bg="#2b2b2b", width=200)
side.pack(side="left", fill="y")

# status
status_label = tk.Label(side, text="● STOPPED", fg="#ff4444", bg="#2b2b2b", font=("Arial", 12))
status_label.pack(pady=15)

# buttons
btn_style = {"width": 18, "bg": "#3a3a3a", "fg": "white", "bd": 0}

tk.Button(side, text="Start", command=start_server, **btn_style).pack(pady=5)
tk.Button(side, text="Stop", command=stop_server, **btn_style).pack(pady=5)
tk.Button(side, text="Open Host", command=open_host, **btn_style).pack(pady=5)

restart_btn = tk.Button(side, text="Auto Restart: ON", command=toggle_restart, **btn_style)
restart_btn.pack(pady=20)

# log box
log_box = tk.Text(root, bg="#121212", fg="#00ffcc", insertbackground="white")
log_box.pack(side="right", fill="both", expand=True, padx=10, pady=10)

update_status()

root.mainloop()