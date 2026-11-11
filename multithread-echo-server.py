import socket
import threading

clients = []

def handle_client(client_socket, addr):
    try:
        while True:
            data = client_socket.recv(1024)
            if not data:
                break
            request = data.decode("utf-8")
            if request.lower() == "close":
                client_socket.sendall("close".encode("utf-8"))
                break
            print(f"Received: {request}")
            #response = "accepted"
            #client_socket.sendall(response.encode("utf-8"))
            for client in clients:
                #if client != client_socket:
                client.sendall(f"Message from {addr[0]}: {request}".encode("utf-8"))

    except Exception as e:
        print(f"Error when handling client {addr[0]}: {e}")
    finally:
        clients.remove(client_socket)
        client_socket.close()
        print(f"Connection with {addr[0]}: {addr[1]} closed")

def run_server():
    host_ip = "0.0.0.0"
    port = 65432

    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.bind((host_ip, port))
        server.listen()
        print(f"Server listening on {host_ip}:{port}")

        while True:
            client_socket, addr = server.accept()
            print(f"Accepted connection from {addr}")
            clients.append(client_socket)
            thread = threading.Thread(target=handle_client, args=(client_socket, addr,))
            thread.start()
    except Exception as e:
        print(f"Error {e}")
    finally:
        server.close()

run_server()