import json
import queue
import socket
import threading
import tkinter as tk
from datetime import datetime

#HOST = "172.20.10.3"
HOST = "10.42.147.245"
PORT = 65432

TYPING_TIMEOUT_MS = 2000  # send "endType" after this long with no key presses

# Classic Windows-style palette
BG = "#d4d0c8"
PANEL = "#ece9d8"
EGGSHELL = "#fffef7"
INK = "#202020"
BLUE = "#1f4e8c"
MUTED = "#58616b"
FONT = ("Tahoma", 10)
FONT_BOLD = ("Tahoma", 10, "bold")


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
        self.root.title("Instant Message")
        self.root.configure(bg=BG)
        self.root.geometry("760x520")
        self.root.minsize(600, 420)
        self.root.protocol("WM_DELETE_WINDOW", self.close_connection)

        menu_bar = tk.Menu(self.root, tearoff=False, bg=BG, fg=INK, activebackground=BLUE,
                           activeforeground="white", font=FONT)
        file_menu = tk.Menu(menu_bar, tearoff=False, bg=BG, fg=INK, font=FONT)
        file_menu.add_command(label="Close", command=self.close_connection)
        menu_bar.add_cascade(label="File", menu=file_menu)
        edit_menu = tk.Menu(menu_bar, tearoff=False, bg=BG, fg=INK, font=FONT)
        edit_menu.add_command(label="Copy", command=self.copy_selection)
        edit_menu.add_command(label="Select All", command=self.select_all)
        menu_bar.add_cascade(label="Edit", menu=edit_menu)
        self.root.configure(menu=menu_bar)

        header = tk.Frame(self.root, bg=BLUE, padx=12, pady=8)
        header.pack(fill="x")
        bubble_icon = tk.Canvas(
            header, width=34, height=28, bg=BLUE, highlightthickness=0,
        )
        bubble_icon.pack(side="left", padx=(0, 8))
        bubble_icon.create_oval(1, 2, 24, 20, fill="#fffef7", outline="#d5e2f2", width=2)
        bubble_icon.create_polygon(5, 17, 3, 25, 12, 19, fill="#fffef7", outline="#d5e2f2")
        bubble_icon.create_oval(11, 9, 33, 26, fill="#ffe28a", outline="#fff1c7", width=2)
        for x in (17, 22, 27):
            bubble_icon.create_oval(x, 16, x + 2, 18, fill="#725a29", outline="")
        tk.Label(
            header, text="Instant Message", font=("Tahoma", 11, "bold"),
            bg=BLUE, fg="white", anchor="w",
        ).pack(side="left")
        tk.Label(
            header, text="Chat with Friend", font=("Tahoma", 9),
            bg=BLUE, fg="#e1eaf5", anchor="e",
        ).pack(side="right")

        conversation = tk.Frame(self.root, bg=BG, padx=10, pady=9)
        tk.Label(
            conversation, text="Conversation", font=FONT_BOLD,
            bg=BG, fg=INK, anchor="w",
        ).pack(fill="x", pady=(0, 5))

        typing_bg = "#fff2c4"
        self.status_frame = tk.Frame(conversation, bg=PANEL, relief="sunken", bd=1)
        self.status_frame.pack(side="bottom", fill="x", pady=(5, 0))
        self.status_icon = tk.Canvas(
            self.status_frame, width=25, height=18, bg=PANEL, highlightthickness=0,
        )
        self.status_icon.pack(side="left", padx=(5, 2))
        self.status_dots = []
        for x in (4, 10, 16):
            self.status_dots.append(
                self.status_icon.create_oval(x, 6, x + 5, 11, fill="#a8a39a", outline=""),
            )
        self.status = tk.Label(
            self.status_frame, text="", font=("Tahoma", 9, "bold"),
            bg=PANEL, fg="#725316", anchor="w", padx=3, pady=4,
        )
        self.status.pack(side="left")

        log_frame = tk.Frame(conversation, bg=BG)
        log_frame.pack(fill="both", expand=True)
        scrollbar = tk.Scrollbar(log_frame, orient="vertical", relief="sunken", bd=1)
        scrollbar.pack(side="right", fill="y")

        self.log = tk.Text(
            log_frame, font=FONT, bg=EGGSHELL, fg=INK, wrap="word", state="disabled",
            relief="sunken", bd=2, padx=9, pady=8, yscrollcommand=scrollbar.set,
        )
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.log.yview)
        self.log.tag_configure("system", foreground=MUTED, font=("Tahoma", 9, "italic"))
        self.log.tag_configure("timestamp", foreground="#77736a")
        self.log.tag_configure("you", foreground="#8b1a1a", font=FONT_BOLD)
        self.log.tag_configure("friend", foreground="#174a7e", font=FONT_BOLD)
        self.log.bind("<Control-a>", self.select_all)
        self.log.bind("<Control-A>", self.select_all)

        composer = tk.Frame(self.root, bg=PANEL, padx=10, pady=8, relief="raised", bd=1)
        composer.pack(side="bottom", fill="x")
        tk.Label(composer, text="Message:", font=FONT, bg=PANEL, fg=INK).grid(
            row=0, column=0, sticky="w", padx=(0, 8),
        )
        self.entry = tk.Entry(
            composer, font=FONT, bg="white", fg=INK, insertbackground=INK,
            relief="sunken", bd=2,
        )
        self.entry.grid(row=0, column=1, sticky="ew", ipady=3)
        self.entry.bind("<Return>", self.send_message)
        self.entry.bind("<KeyRelease>", self.on_key)
        self.root.after(100, self.entry.focus_set)

        buttons = tk.Frame(composer, bg=PANEL)
        buttons.grid(row=0, column=2, padx=(8, 0))
        for text, command in (("Send", self.send_message), ("Close", self.close_connection)):
            tk.Button(
                buttons, text=text, command=command, font=FONT,
                bg=BG, fg=INK, activebackground="#c8c4ba", activeforeground=INK,
                relief="raised", bd=2, padx=10,
            ).pack(side="left", padx=(0, 5))
        composer.grid_columnconfigure(1, weight=1)
        conversation.pack(fill="both", expand=True)

    def write_line(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.configure(state="disabled")
        self.log.see("end")

    def write_message(self, timestamp, sender, text, sender_tag):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{timestamp}] ", "timestamp")
        self.log.insert("end", f"{sender}: ", sender_tag)
        self.log.insert("end", text + "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def select_all(self, event=None):
        self.log.tag_add("sel", "1.0", "end")
        return "break"

    def copy_selection(self):
        try:
            selected = self.log.get("sel.first", "sel.last")
        except tk.TclError:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)

    def set_friend_typing(self, is_typing):
        if is_typing:
            self.status.configure(text="FRIEND IS TYPING...", bg="#fff2c4")
            self.status_frame.configure(bg="#fff2c4")
            self.status_icon.configure(bg="#fff2c4")
            for dot in self.status_dots:
                self.status_icon.itemconfigure(dot, fill="#d99b24")
        else:
            self.status.configure(text="", bg=PANEL)
            self.status_frame.configure(bg=PANEL)
            self.status_icon.configure(bg=PANEL)
            for dot in self.status_dots:
                self.status_icon.itemconfigure(dot, fill="#a8a39a")

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
            self.set_friend_typing(False)
            if self.closing:
                self.root.destroy()
            else:
                self.write_line("*** SERVER DISCONNECTED ***", "system")
            return

        msg_type = packet.get("type")
        if msg_type == "message":
            self.set_friend_typing(False)
            self.write_message(
                packet.get("timestamp"), "Friend", packet.get("message"), "friend",
            )
        elif msg_type == "startType":
            self.set_friend_typing(True)
        elif msg_type == "endType":
            self.set_friend_typing(False)
        elif msg_type == "close":
            self.set_friend_typing(False)
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
        self.write_message(packet["timestamp"], "You", text, "you")
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
