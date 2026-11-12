import socket
import threading
import json
from datetime import datetime

# Every packet is one line of JSON with three parts:
#   type      = "message", "close", "startType", or "endType"
#   message   = the text being sent (empty for everything except "message")
#   timestamp = when it was sent, e.g. "2026-11-12 16:27:00"
#
# Each packet ends with a newline ("\n") so that two packets arriving
# back-to-back (like endType followed by message) can be told apart.

clients = []
clients_lock = threading.Lock()


def make_packet(msg_type, message=""):
    return {
        "type": msg_type,
        "message": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def send_packet(sock, packet):
    sock.sendall((json.dumps(packet) + "\n").encode("utf-8"))


def broadcast(packet, sender_socket):
    """Send a packet to every client except the one it came from."""
    with clients_lock:
        others = [c for c in clients if c != sender_socket]
    for client in others:
        try:
            send_packet(client, packet)
        except OSError:
            pass  # that client's own thread will clean it up


def handle_client(client_socket, addr):
    buffer = ""
    try:
        open_connection = True
        while open_connection:
            data = client_socket.recv(1024)
            if not data:
                break
            buffer += data.decode("utf-8")

            # Pull out every complete line (one line = one packet)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    print("Invalid JSON received")
                    continue
                print(f"Received from {addr[0]}: {request}")

                msg_type = request.get("type")
                if msg_type == "close":
                    send_packet(client_socket, make_packet("close"))
                    open_connection = False
                    break
                elif msg_type in ("message", "startType", "endType"):
                    broadcast(request, client_socket)
                else:
                    print(f"Unknown type: {msg_type}")

    except Exception as e:
        print(f"Error when handling client {addr[0]}: {e}")
    finally:
        with clients_lock:
            if client_socket in clients:
                clients.remove(client_socket)
        client_socket.close()
        # Let everyone else know this user is gone
        broadcast(make_packet("close"), client_socket)
        print(f"Connection with {addr[0]}:{addr[1]} closed")


def run_server():
    host_ip = "0.0.0.0"
    port = 65432

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((host_ip, port))
        server.listen()
        print(f"Server listening on {host_ip}:{port}")

        while True:
            client_socket, addr = server.accept()
            print(f"Accepted connection from {addr}")
            with clients_lock:
                clients.append(client_socket)
            thread = threading.Thread(
                target=handle_client, args=(client_socket, addr), daemon=True
            )
            thread.start()
    except Exception as e:
        print(f"Error {e}")
    finally:
        server.close()


if __name__ == "__main__":
    run_server()