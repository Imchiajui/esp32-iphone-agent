"""Link to the HID bridge board: TCP over Wi-Fi (see firmware/hid_bridge), or the board's USB serial port
(BLE bridge built with SERIAL_LINK=1, see hardware/hid_bridge_ble_c3)."""

import asyncio
import logging
import threading
import time

log = logging.getLogger(__name__)

# USB to UART chips and native USB found on ESP32 boards: CP210x, CH340, FTDI, Espressif
BOARD_VIDS = (0x10C4, 0x1A86, 0x0403, 0x303A)


class DeviceError(RuntimeError):
    pass


class SerialLink:
    """A pyserial port with the reader/writer methods Device uses. A thread reads lines; readline() returns only
    replies ("ok..." / "err..."), so the ESP32 boot banner and the board's greeting never pass for an answer."""

    def __init__(self, port, loop: asyncio.AbstractEventLoop):
        self._port, self._loop = port, loop
        self._lines: asyncio.Queue[bytes] = asyncio.Queue()
        self._closed = False
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        buf = b""
        while not self._closed:
            try:
                chunk = self._port.read(self._port.in_waiting or 1)
            except Exception as e:  # unplugged: pyserial raises SerialException (an OSError) or worse on Windows
                log.debug("serial read failed: %r", e)
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._loop.call_soon_threadsafe(self._lines.put_nowait, line + b"\n")
        self._closed = True
        self._loop.call_soon_threadsafe(self._lines.put_nowait, b"")  # end of stream

    async def readline(self) -> bytes:
        while True:
            line = await self._lines.get()
            if not line:
                self._lines.put_nowait(b"")  # stay at end of stream for any later reader
                return b""
            text = line.strip()
            if text.startswith((b"ok", b"err")):
                return line
            if text:
                log.debug("board says: %s", text.decode(errors="replace"))

    def write(self, data: bytes) -> None:
        if self._closed:
            raise ConnectionResetError("serial port closed")
        try:
            self._port.write(data)
        except Exception as e:
            self.close()
            raise ConnectionResetError(f"serial write failed: {e!r}") from e

    async def drain(self) -> None:
        pass

    def discard(self) -> None:
        """Drop lines already read but not consumed (late replies to an earlier sync)."""
        while not self._lines.empty():
            line = self._lines.get_nowait()
            if not line:
                self._lines.put_nowait(b"")
                return

    def is_closing(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True
        try:
            self._port.close()
        except Exception:
            pass

    def get_extra_info(self, key, default=None):
        return getattr(self._port, "port", default) if key == "peername" else default


def find_serial_port() -> str | None:
    """The first serial port that looks like an ESP32 board, by USB vendor id."""
    from serial.tools import list_ports

    for p in sorted(list_ports.comports(), key=lambda p: p.device):
        if p.vid in BOARD_VIDS:
            return p.device
    return None


def open_serial(name: str, baud: int = 115200):
    import serial

    port = serial.Serial()
    port.port, port.baudrate, port.timeout, port.write_timeout = name, baud, 0.2, 2
    # Dev boards wire DTR/RTS to EN and GPIO0 (auto-reset). Keep both released so opening the port does not
    # reset the board or drop it into the bootloader.
    port.dtr = port.rts = False
    port.open()
    return port


class Device:
    """Accepts one board connection and sends it commands, one at a time."""

    def __init__(self):
        self._reader = self._writer = None
        self._lock = asyncio.Lock()
        self._last = self._beat = 0.0
        self.links = 0  # bumped on every (re)connect, so gestures know to release and re-home

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def serve(self, host: str, port: int):
        return await asyncio.start_server(self._accept, host, port)

    async def _accept(self, reader, writer):
        # newer firmware greets with "hello <last reset reason> <uptime ms>": read it before any command
        try:
            hello = (await asyncio.wait_for(reader.readline(), 1)).decode().strip()
        except (OSError, asyncio.TimeoutError):
            hello = ""
        if self.connected:
            self._writer.close()
        self._reader, self._writer = reader, writer
        self.links += 1
        self._last = self._beat = time.time()  # fresh link: nothing to keep awake yet
        log.info("board connected from %s %s", writer.get_extra_info("peername"), hello)

    async def serial(self, name: str, baud: int = 115200, retry: float = 2) -> None:
        """Keep a board on a serial port attached: open it (name "auto" picks the first ESP32-like USB port),
        sync, and reopen whenever it is unplugged or stops answering. Runs until cancelled."""
        while True:
            port_name = await asyncio.to_thread(find_serial_port) if name.lower() == "auto" else name
            if not port_name:
                await asyncio.sleep(retry)
                continue
            try:
                port = await asyncio.to_thread(open_serial, port_name, baud)
            except Exception as e:  # missing driver, port busy (e.g. the flasher still has it), unplugged
                log.info("cannot open %s: %s", port_name, e)
                await asyncio.sleep(retry)
                continue
            link = SerialLink(port, asyncio.get_running_loop())
            try:
                await self.attach_serial(link)
            except DeviceError as e:
                log.info("board on %s did not answer: %s", port_name, e)
                link.close()
                await asyncio.sleep(retry)
                continue
            while not link.is_closing():
                await asyncio.sleep(0.5)
            log.info("board on %s gone", port_name)

    async def attach_serial(self, link, attempts: int = 8) -> str:
        """Find the start of the conversation on a fresh serial link (the board may still be booting) and make it
        the current board."""
        for attempt in range(attempts):
            reset = getattr(getattr(link, "_port", None), "reset_input_buffer", None)
            if reset:
                reset()
            link.write(b"\nsync\n")
            try:
                reply = (await asyncio.wait_for(link.readline(), 1)).decode().strip()
            except asyncio.TimeoutError:
                continue
            if not reply and link.is_closing():
                break
            if reply.startswith("ok hello"):
                # an earlier sync that timed out may still be answered: let it arrive, then drop it, so the next
                # command does not read a stale reply
                await asyncio.sleep(0.2 if attempt == 0 else 1.2)
                link.discard()
                if self.connected:
                    self._writer.close()
                self._reader = self._writer = link
                self.links += 1
                self._last = self._beat = time.time()
                log.info("board connected on %s: %s", link.get_extra_info("peername"), reply[3:])
                return reply[3:]
        raise DeviceError("no reply to sync (is the firmware built with SERIAL_LINK=1?)")

    async def wait_connected(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while not self.connected and time.time() < deadline:
            await asyncio.sleep(0.2)
        return self.connected

    @staticmethod
    def _timeout(command: str) -> float:
        """Seconds the board may take: Wi-Fi replies need up to ~2 s at p99, moves are paced
        (10 units per 8 ms), typing is per character."""
        name, _, arg = command.partition(" ")
        if name == "move":
            return 5 + max(abs(int(n)) for n in arg.split()) / 10 * 0.012
        if name == "type":
            return 5 + 0.1 * len(arg)
        if name == "ping":
            return 8  # an idle check: tolerate a Wi-Fi hiccup rather than drop a healthy board
        return 5

    async def send(self, command: str) -> None:
        if not self.connected:
            raise DeviceError("board not connected")
        timeout = self._timeout(command)
        async with self._lock:
            if not self.connected:  # a preceding command may have closed the link while this one waited
                raise DeviceError("board not connected")
            reader, writer = self._reader, self._writer
            started = time.time()
            try:
                writer.write(command.encode() + b"\n")
                await writer.drain()
                reply = (await asyncio.wait_for(reader.readline(), timeout)).decode().strip()
            except asyncio.CancelledError:
                writer.close()  # discard the pending reply before another command can consume it
                raise
            except (OSError, asyncio.TimeoutError) as e:
                writer.close()  # close this command's connection, not a replacement accepted while waiting
                raise DeviceError(f"board link lost during '{command[:30]}': {e!r}") from e
        self._beat = time.time()  # last reply of any kind
        if command != "ping":
            self._last = self._beat  # last real command: the phone's idle time
            log.debug("%s -> %s (%.0f ms)", command, reply, (time.time() - started) * 1000)
        if reply != "ok":
            raise DeviceError(reply or "board disconnected")

    async def keep_awake(self, idle: float = 25, heartbeat: float = 2, screen=None) -> None:
        """While idle: ping every few seconds, so a board that was unplugged or hung shows as gone within
        seconds (not at the next command), and nudge the pointer now and then so the phone does not auto-lock."""
        while True:
            await asyncio.sleep(heartbeat)
            if not self.connected or time.time() - self._beat < heartbeat:
                continue
            try:
                # nudge only a phone that is awake and mirroring: moving a sleeping phone's pointer can stall the
                # board on its USB link, and there is nothing to keep awake anyway
                if time.time() - self._last > idle and (screen is None or screen.live):
                    await self.send("move 1 0")
                    await self.send("move -1 0")
                else:
                    await self.send("ping")
            except DeviceError as e:
                log.info("board gone: %s", e)
