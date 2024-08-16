import asyncio
import fcntl
import os
import pty
import shlex
import struct
import tempfile
import termios

import pyte
from rich.console import RenderableType
from rich.text import Text
from textual import events
from textual.widget import Widget


CTRL_KEYS = {
    "left": "\u001b[D",
    "right": "\u001b[C",
    "up": "\u001b[A",
    "down": "\u001b[B",
}


class PyteDisplay:
    def __init__(self, lines):
        self.lines = lines

    def __rich_console__(self, console, options):
        for line in self.lines:
            yield line


class Terminal(Widget, can_focus=True):
    DEFAULT_CSS = """
    _Terminal {
        height: 1fr;
    }
    """

    def __init__(self, send_queue, recv_queue):
        super().__init__()
        self._send_queue = send_queue
        self._recv_queue = recv_queue
        self._display = PyteDisplay([Text()])
        self.size_set = asyncio.Event()
        self._background_tasks = set()
        task = asyncio.create_task(self._recv())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def render(self) -> RenderableType:
        return self._display

    def on_resize(self, event: events.Resize):
        self._ncol = event.size.width
        self._nrow = event.size.height
        self._screen = pyte.Screen(self._ncol, self._nrow)
        self._stream = pyte.Stream(self._screen)
        self.size_set.set()

    async def on_key(self, event: events.Key) -> None:
        char = CTRL_KEYS.get(event.key) or event.character
        await self._send_queue.put(["stdin", char])
        event.stop()

    async def _recv(self):
        await self.size_set.wait()
        while True:
            message = await self._recv_queue.get()
            cmd = message[0]
            if cmd == "setup":
                await self._send_queue.put(["set_size", self._nrow, self._ncol, 567, 573])
            elif cmd == "stdout":
                chars = message[1]
                self._stream.feed(chars)
                lines = []
                for i, line in enumerate(self._screen.display):
                    text = Text.from_ansi(line)
                    x = self._screen.cursor.x
                    if i == self._screen.cursor.y and x < len(text):
                        cursor = text[x]
                        cursor.stylize("reverse")
                        new_text = text[:x]
                        new_text.append(cursor)
                        new_text.append(text[x + 1 :])
                        text = new_text
                    lines.append(text)
                self._display = PyteDisplay(lines)
                self.refresh()


class Vim(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._send_queue = asyncio.Queue()
        self._recv_queue = asyncio.Queue()
        self._data_or_disconnect = None
        self._event = asyncio.Event()
        self.terminal = Terminal(self._recv_queue, self._send_queue)
        self.terminal.focus()
        self._background_tasks = set()
        task = asyncio.create_task(self._run())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        task = asyncio.create_task(self._send())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _open_vim(self):
        pid, fd = pty.fork()
        if pid == 0:
            tmpf = tempfile.NamedTemporaryFile(delete=False)
            argv = shlex.split(f"vim {tmpf.name}")
            #argv = shlex.split(f"bash")
            env = dict(
                TERM="linux",
                LC_ALL="en_GB.UTF-8",
                COLUMNS=str(self._ncol),
                LINES=str(self._nrow),
            )
            os.execvpe(argv[0], argv, env)
        return fd

    async def _run(self):
        await asyncio.sleep(1)
        self.mount(self.terminal)
        await self.terminal.size_set.wait()
        self._ncol = self.terminal.size.width
        self._nrow = self.terminal.size.height
        self._fd = self._open_vim()
        self._p_out = os.fdopen(self._fd, "w+b", 0)

        loop = asyncio.get_running_loop()

        def on_output():
            try:
                self._data_or_disconnect = self._p_out.read(65536).decode()
                self._event.set()
            except Exception:
                loop.remove_reader(self._p_out)
                self._data_or_disconnect = None
                self._event.set()

        loop.add_reader(self._p_out, on_output)
        await self._send_queue.put(["setup", {}])
        while True:
            msg = await self._recv_queue.get()
            if msg[0] == "stdin":
                self._p_out.write(msg[1].encode())
            elif msg[0] == "set_size":
                winsize = struct.pack("HH", msg[1], msg[2])
                fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)

    async def _send(self):
        while True:
            await self._event.wait()
            self._event.clear()
            if self._data_or_disconnect is None:
                await self._send_queue.put(["disconnect", 1])
            else:
                await self._send_queue.put(["stdout", self._data_or_disconnect])
