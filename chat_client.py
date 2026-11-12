import json
import queue
import socket
import threading
import tkinter as tk
from datetime import datetime

#HOST = "172.20.10.3"
HOST = "10.42.159.253"
PORT = 65432

TYPING_TIMEOUT_MS = 2000  # send "endType" after this long with no key presses

# Old-school terminal look
BG = "#000000"
FG = "#33ff33"
DIM = "#1c8c1c"
FONT = ("Courier", 12)
FONT_BOLD = ("Courier", 12, "bold")


def make_packet(msg_type, message=""):
    """Every packet has the same three parts: type, message, timestamp."""
    return {
        "type": msg_type,  # "message", "close", "startType", or "endType"
        "message": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


class ChatClient:
    def __init__(self, root):
        self.root = root
        self.sock = None
        self.connected = False
        self.closing = False
        self.typing = False        # have we sent startType without an endType yet?
        self.typing_timer = None   # id of the pending "stop typing" timer
        self.incoming = queue.Queue()  # packets handed from the socket thread to the GUI

        self.build_gui()
        self.connect()
        self.root.after(100, self.check_incoming)

    # ---------------- GUI ----------------

    def build_gui(self):
        self.root.title("TERMINAL CHAT")
        self.root.configure(bg=BG)
        self.root.geometry("720x480")
        self.root.protocol("WM_DELETE_WINDOW", self.close_connection)

        header = tk.Label(
            self.root, text="*** TERMINAL CHAT v1.0 ***", font=FONT_BOLD,
            bg=FG, fg=BG, anchor="w", padx=8,
        )
        header.pack(fill="x")

        # Bottom row: prompt, entry box, buttons
        bottom = tk.Frame(self.root, bg=BG)
        bottom.pack(side="bottom", fill="x", padx=8, pady=8)

        tk.Label(bottom, text=">", font=FONT_BOLD, bg=BG, fg=FG).pack(side="left")

        self.entry = tk.Entry(
            bottom, font=FONT, bg=BG, fg=FG, insertbackground=FG, insertwidth=8,
            relief="flat", highlightthickness=1,
            highlightbackground=DIM, highlightcolor=FG,
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=6, ipady=3)
        self.entry.bind("<Return>", self.send_message)
        self.entry.bind("<KeyRelease>", self.on_key)
        self.entry.focus_set()

        for text, command in (("[ SEND ]", self.send_message), ("[ CLOSE ]", self.close_connection)):
            tk.Button(
                bottom, text=text, command=command, font=FONT_BOLD,
                bg=BG, fg=FG, activebackground=FG, activeforeground=BG,
                relief="flat", bd=0, highlightthickness=1, highlightbackground=DIM,
            ).pack(side="left", padx=2)

        # Status line: shows when the other person is typing
        self.status = tk.Label(
            self.root, text="", font=FONT, bg=BG, fg=DIM, anchor="w", padx=8,
        )
        self.status.pack(side="bottom", fill="x")

        # Message log
        self.log = tk.Text(
            self.root, font=FONT, bg=BG, fg=FG, wrap="word", state="disabled",
            relief="flat", highlightthickness=1, highlightbackground=DIM,
            padx=8, pady=6,
        )
        self.log.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.log.tag_configure("system", foreground=DIM)

    def write_line(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.configure(state="disabled")
        self.log.see("end")

    # ---------------- Networking ----------------

    def connect(self):
        self.write_line(f"CONNECTING TO {HOST}:{PORT} ...", "system")
        try:
            self.sock = socket.create_connection((HOST, PORT), timeout=5)
            self.sock.settimeout(None)
        except OSError as error:
            self.write_line(f"*** CONNECTION FAILED: {error} ***", "system")
            return
        self.connected = True
        self.write_line("*** CONNECTED. TYPE A MESSAGE AND PRESS ENTER. ***", "system")
        threading.Thread(target=self.receive_messages, daemon=True).start()

    def send_packet(self, packet):
        if not self.connected:
            return
        try:
            # The newline marks the end of the packet
            self.sock.sendall((json.dumps(packet) + "\n").encode("utf-8"))
        except OSError as error:
            self.connected = False
            self.write_line(f"*** CONNECTION ERROR: {error} ***", "system")

    def receive_messages(self):
        """Runs in a background thread. Never touches the GUI directly."""
        buffer = ""
        while True:
            try:
                data = self.sock.recv(1024)
            except OSError:
                data = b""
            if not data:
                self.incoming.put(None)  # None = server disconnected
                return
            buffer += data.decode("utf-8")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip():
                    continue
                try:
                    self.incoming.put(json.loads(line))
                except json.JSONDecodeError:
                    pass

    def check_incoming(self):
        """Runs on the GUI thread every 100 ms to show whatever has arrived."""
        try:
            while True:
                self.handle_packet(self.incoming.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.check_incoming)

    def handle_packet(self, packet):
        if packet is None:
            self.connected = False
            self.status.configure(text="")
            if self.closing:
                self.root.destroy()
            else:
                self.write_line("*** SERVER DISCONNECTED ***", "system")
            return

        msg_type = packet.get("type")
        if msg_type == "message":
            self.status.configure(text="")
            self.write_line(f"[{packet.get('timestamp')}] <FRIEND> {packet.get('message')}")
        elif msg_type == "startType":
            self.status.configure(text="FRIEND IS TYPING...")
        elif msg_type == "endType":
            self.status.configure(text="")
        elif msg_type == "close":
            self.status.configure(text="")
            if self.closing:
                self.root.destroy()  # server confirmed our close
            else:
                self.write_line("*** FRIEND HAS LEFT THE CHAT ***", "system")

    # ---------------- Sending ----------------

    def on_key(self, event):
        """Called on every key press in the entry box to track typing."""
        if event.keysym == "Return":
            return
        if self.entry.get():
            if not self.typing:
                self.typing = True
                self.send_packet(make_packet("startType"))
            # Restart the countdown to "endType"
            if self.typing_timer is not None:
                self.root.after_cancel(self.typing_timer)
            self.typing_timer = self.root.after(TYPING_TIMEOUT_MS, self.stop_typing)
        else:
            self.stop_typing()  # box was emptied

    def stop_typing(self):
        if self.typing_timer is not None:
            self.root.after_cancel(self.typing_timer)
            self.typing_timer = None
        if self.typing:
            self.typing = False
            self.send_packet(make_packet("endType"))

    def send_message(self, event=None):
        text = self.entry.get().strip()
        if not text or not self.connected:
            return
        self.stop_typing()  # sending a message also ends typing
        packet = make_packet("message", text)
        self.send_packet(packet)
        self.write_line(f"[{packet['timestamp']}] <YOU> {text}")
        self.entry.delete(0, "end")

    def close_connection(self):
        if not self.connected or self.closing:
            self.root.destroy()
            return
        self.closing = True
        self.stop_typing()
        self.send_packet(make_packet("close"))
        self.write_line("*** CLOSING CONNECTION ... ***", "system")
        # Close anyway if the server never answers
        self.root.after(1500, self.root.destroy)


if __name__ == "__main__":
    root = tk.Tk()
    ChatClient(root)
    root.mainloop()
