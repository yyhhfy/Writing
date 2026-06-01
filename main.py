import sys

from PyQt6.QtCore import Qt
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from main_window import MainWindow


INSTANCE_NAME = "writing_tool_single_instance"


def notify_existing_instance():
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.flush()
    if not socket.waitForBytesWritten(300):
        return False
    if not socket.waitForReadyRead(700):
        socket.disconnectFromServer()
        return False
    response = bytes(socket.readAll()).decode("utf-8", errors="ignore")
    socket.disconnectFromServer()
    return "ok" in response


def create_instance_server(window):
    QLocalServer.removeServer(INSTANCE_NAME)
    server = QLocalServer(window)
    if not server.listen(INSTANCE_NAME):
        return None

    def on_new_connection():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            client.readyRead.connect(lambda c=client: _handle_instance_message(c, window))

    server.newConnection.connect(on_new_connection)
    return server


def _handle_instance_message(client, window):
    message = bytes(client.readAll()).decode("utf-8", errors="ignore")
    if "show" in message:
        window.show_existing_instance()
        client.write(b"ok")
        client.flush()
        client.waitForBytesWritten(300)
    client.disconnectFromServer()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Writing")
    app.setQuitOnLastWindowClosed(False)

    if notify_existing_instance():
        return

    window = MainWindow()
    window.instance_server = create_instance_server(window)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
