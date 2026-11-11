
import socket
import threading
import json

HOST = "172.20.10.3"
PORT = 65432


def receive_messages(sock, disconnected):
    while True:
        try:
            data = sock.recv(1024)
        except OSError as error:
            if not disconnected.is_set():
                print(f"\nConnection error: {error}", flush=True)
                disconnected.set()
            return

        if not data:
            disconnected.set()
            print("\nServer disconnected.", flush=True)
            return

        print(f"\nReceived: {data.decode('utf-8')}", flush=True)


with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.connect((HOST, PORT))

    disconnected = threading.Event()
    receiver = threading.Thread(
        target=receive_messages, args=(s, disconnected), daemon=True
    )
    receiver.start()

    while not disconnected.is_set():
        message = input("Enter a message (or 'close' to exit): ")
        data = {
            "message": message,
            "timestamp": 30,
            "closing": False
        }
        s.sendall(json.dumps(data).encode("utf-8"))
        if message.lower() == "close":
            break

    receiver.join()
