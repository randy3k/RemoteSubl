import sublime
import sublime_plugin
import os
import tempfile
import socket
import subprocess
from time import strftime
from threading import Thread
import socketserver


CREATE_TEMP_FILE_ERROR = "Failed to create remote_subl temporary directory! Error: {}"
WRITE_TEMP_FILE_ERROR = "Failed to write to temp file! Error: {}"
CONNECTION_LOST = "Connection to {} is lost."
FILES = {}
LOST_FILES = {}
server = None


def subl(*args):
    executable_path = sublime.executable_path()
    if sublime.platform() == 'osx':
        app_path = executable_path[:executable_path.rfind('.app/') + 5]
        executable_path = app_path + 'Contents/SharedSupport/bin/subl'

    subprocess.Popen([executable_path] + list(args))

    def on_activated():
        window = sublime.active_window()
        view = window.active_view()

        if sublime.platform() == 'windows':
            # fix focus on windows
            window.run_command('focus_neighboring_group')
            window.focus_view(view)

        sublime_plugin.on_activated(view.id())
        sublime_plugin.on_activated_async(view.id())

    sublime.set_timeout(on_activated, 300)


def say(msg):
    print('[remote_subl {}]: {}'.format(strftime("%H:%M:%S"), msg))


class File:
    def __init__(self, session):
        self.session = session
        self.env = {}
        self.data = [] # list of bytes
        self.current_data_length = 0
        self.file_size = None # The total length that we plan to read
        self.ready = False

    def append(self, line):
        # If appending this line would put us over the stated file size
        if self.current_data_length + len(line) > self.file_size:
            # Trim
            line = line[:(self.file_size - self.current_data_length)]
            assert len(line) + self.current_data_length == self.file_size

        self.data.append(line)
        self.current_data_length += len(line)

        # If we're done, end
        if self.current_data_length == self.file_size:
            self.ready = True

    def get_text(self):
        return b"".join(self.data)

    def close(self, remove=True):
        self.session.send("close")
        self.session.send("token: {}".format(self.env['token']))
        self.session.send("")
        if remove:
            os.unlink(self.temp_path)
            os.rmdir(self.temp_dir)
        self.session.try_close()

    def save(self):
        self.session.send("save")
        self.session.send("token: {}".format(self.env['token']))
        temp_file = open(self.temp_path, "rb")
        new_file = temp_file.read()
        temp_file.close()
        self.session.send("data: {:d}".format(len(new_file)))
        self.session.send(new_file)

    def get_temp_dir(self):
        # First determine if the file has been sent before.
        for f in FILES.values():
            if f.env["real-path"] and f.env["real-path"] == self.env["real-path"] and \
                    f.host and f.host == self.host:
                return f.temp_dir

        for vid, f in list(LOST_FILES.items()):
            if f.env["real-path"] and f.env["real-path"] == self.env["real-path"] and \
                    f.host and f.host == self.host:
                LOST_FILES.pop(vid)
                return f.temp_dir

        # Create a secure temporary directory, both for privacy and to allow
        # multiple files with the same basename to be edited at once without
        # overwriting each other.
        try:
            return tempfile.mkdtemp(prefix=(self.host or "remote_subl") + "-")
        except OSError as e:
            sublime.message_dialog(CREATE_TEMP_FILE_ERROR.format(e))

    def open(self):
        self.temp_dir = self.get_temp_dir()
        self.temp_path = os.path.join(
            self.temp_dir,
            self.base_name)
        try:
            with open(self.temp_path, "wb+") as temp_file:
                temp_file.write(self.get_text())
                temp_file.flush()
        except IOError as e:
            try:
                # Remove the file if it exists.
                os.remove(self.temp_path)
                os.rmdir(self.temp_dir)
            except Exception:
                pass

            sublime.message_dialog(WRITE_TEMP_FILE_ERROR.format(e))

        # create new window if needed
        if len(sublime.windows()) == 0 or "new" in self.env:
            sublime.run_command("new_window")

        # Open it within sublime
        view = sublime.active_window().open_file(
            "{0}:{1}:0".format(
                self.temp_path, self.env['selection'] if 'selection' in self.env else 0),
            sublime.ENCODED_POSITION)

        # Add the file metadata to the view's settings
        view.settings().set('remote_subl.host', self.host)
        view.settings().set('remote_subl.base_name', self.base_name)

        # if the current view is attached to another file object,
        # that file object has to be closed first.
        if view.id() in FILES:
            file = FILES.pop(view.id())
            try:
                # connection may have lost
                file.close(remove=False)
            except Exception:
                pass

        # Add the file to the global list
        FILES[view.id()] = self

        # Bring sublime to front by running `subl --command ""`
        subl("--command", "")

        # Optionally set the color scheme
        settings = sublime.load_settings("remote_subl.sublime-settings")
        color_scheme = settings.get("color_scheme", None)
        if color_scheme is not None:
            subl("--command", 'set_setting {{"setting":"color_scheme","value":"{}"}}'.format(color_scheme))

        view.run_command("remote_subl_update_status_bar")


class Session:
    def __init__(self, socket):
        self.socket = socket
        self.parsing_data = False
        self.nconn = 0
        self.file = None

    def parse_input(self, input_line):
        if not self.parsing_data:
            if input_line.strip() == b"open":
                self.file = File(self)
                self.nconn += 1
                return

        if self.parsing_data:
            self.file.append(input_line)
            if self.file.ready:
                self.file.open()
                self.parsing_data = False
                self.file = None
            return

        if not self.file:
            return

        # prase settings
        input_line = input_line.decode("utf8").strip()
        if ":" not in input_line:
            # not a setting
            return

        k, v = input_line.split(":", 1)
        k = k.strip()
        v = v.strip()
        self.file.env[k] = v

        if k == "data":
            self.file.file_size = int(v)
            self.parsing_data = True

            if ":" in self.file.env["display-name"]:
                host, base_name = self.file.env["display-name"].split(":", 1)
                self.file.host = host
                self.file.base_name = os.path.basename(base_name)
            else:
                self.file.host = None
                self.file.base_name = os.path.basename(self.file.env["display-name"])

            if self.file.env["token"] == "-":
                # stdin input
                self.file.base_name = "untitled"

    def send(self, string):
        if not isinstance(string, bytes):
            string = string.encode("utf8")
        self.socket.send(string + b"\n")

    def try_close(self):
        self.nconn -= 1
        if self.nconn == 0:
            self.socket.shutdown(socket.SHUT_RDWR)
            self.socket.close()


class RemoteSublEventListener(sublime_plugin.EventListener):
    def on_post_save_async(self, view):
        base_name = view.settings().get('remote_subl.base_name')
        if base_name:
            host = view.settings().get('remote_subl.host', "remote server")
            try:
                file = FILES[view.id()]
                file.save()
                say('Saved {} to {}.'.format(base_name, host))

                sublime.set_timeout(
                    lambda: sublime.status_message("Saved {} to {}.".format(
                        base_name, host)))
            except Exception:
                say('Error saving {} to {}.'.format(base_name, host))
                sublime.set_timeout(
                    lambda: sublime.status_message(
                        "Error saving {} to {}.".format(base_name, host)))

    def on_close(self, view):
        base_name = view.settings().get('remote_subl.base_name')
        if base_name:
            host = view.settings().get('remote_subl.host', "remote server")
            vid = view.id()
            if vid in LOST_FILES:
                LOST_FILES.pop(vid)
            try:
                file = FILES.pop(vid)
                file.close()
                say('Closed {} in {}.'.format(base_name, host))
            except Exception:
                say('Error closing {} in {}.'.format(base_name, host))

    def on_activated(self, view):
        base_name = view.settings().get('remote_subl.base_name')
        if base_name:
            view.run_command("remote_subl_update_status_bar")


class RemoteSublUpdateStatusBarCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        view = self.view
        if view.id() in FILES:
            file = FILES[view.id()]
            server_name = file.host or "remote server"
            self.view.set_status("remotesub_status", "[{}]".format(server_name))
        else:
            self.view.set_status("remotesub_status", "[connection lost]")


class ConnectionHandler(socketserver.BaseRequestHandler):
    def handle(self):
        address = str(self.client_address)

        say('New connection from ' + address)

        session = Session(self.request)
        self.request.send(b"Sublime Text 3 (remote_subl plugin)\n")

        socket_fd = self.request.makefile("rb")
        while True:
            line = socket_fd.readline()
            if len(line) == 0:
                break
            session.parse_input(line)

        self.cleanup(session)
        say('Connection from {} is closed.'.format(address))

    def cleanup(self, session):
        settings = sublime.load_settings("remote_subl.sublime-settings")
        vid_to_pop = []
        for vid, file in list(FILES.items()):
            if file.session == session:
                # only show message once
                if not vid_to_pop:
                    if settings.get("pop_up_when_connection_lost", True):
                        sublime.message_dialog(
                            CONNECTION_LOST.format(file.host or "remote"))
                vid_to_pop.append(vid)

        for vid in vid_to_pop:
            LOST_FILES[vid] = FILES.pop(vid)
            sublime.View(vid).run_command("remote_subl_update_status_bar")


class TCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def plugin_unloaded():
    global server
    say('Killing server...')
    if server:
        server.shutdown()
        server.server_close()


def plugin_loaded():
    global server

    # Load settings
    settings = sublime.load_settings("remote_subl.sublime-settings")
    port = settings.get("port", 52698)
    host = settings.get("host", "localhost")

    # Start server thread
    server = TCPServer((host, port), ConnectionHandler)
    Thread(target=server.serve_forever, args=[]).start()
    say('Server running on {}:{} ...'.format(host, str(port)))
