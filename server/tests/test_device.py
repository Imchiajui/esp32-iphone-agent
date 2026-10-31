import asyncio

import pytest

from hidagent.device import Device, DeviceError


def test_timeout_grows_with_move_distance_and_text_length():
    assert Device._timeout("click") == 5
    assert Device._timeout("move 1000 -20") > Device._timeout("move 10 10") >= 5
    assert Device._timeout("type " + "x" * 40) > Device._timeout("type hi")


def test_send_without_board_fails_fast():
    with pytest.raises(DeviceError, match="not connected"):
        asyncio.run(Device().send("ping"))


def test_round_trip_with_a_fake_board():
    async def scenario():
        device = Device()
        server = await device.serve("127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        reader, writer = await asyncio.open_connection("127.0.0.1", port)

        async def board():  # answers every command like the firmware does
            while line := await reader.readline():
                writer.write(b"ok\n" if line.strip() != b"bad" else b"err unknown command\n")
                await writer.drain()

        task = asyncio.create_task(board())
        assert await device.wait_connected(2)
        await device.send("ping")
        with pytest.raises(DeviceError, match="unknown command"):
            await device.send("bad")
        assert device.links == 1
        task.cancel()
        writer.close()
        server.close()

    asyncio.run(scenario())


def test_old_request_failure_does_not_close_replacement_connection():
    class Writer:
        def __init__(self):
            self.closed = False
        def is_closing(self): return self.closed
        def close(self): self.closed = True
        def write(self, data): pass
        async def drain(self): pass
        def get_extra_info(self, key): return ("fake-board", 7300)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class OldReader:
            async def readline(self):
                entered.set()
                await release.wait()
                raise OSError("old connection lost")

        class NewReader:
            def __init__(self): self.first = True
            async def readline(self):
                if self.first:
                    self.first = False
                    return b"hello power-on 123\n"
                return b"ok\n"

        device = Device()
        old, replacement = Writer(), Writer()
        device._reader, device._writer = OldReader(), old
        pending = asyncio.create_task(device.send("ping"))
        await entered.wait()
        await device._accept(NewReader(), replacement)
        release.set()
        with pytest.raises(DeviceError, match="old connection lost"):
            await pending
        assert old.closed
        assert device.connected and not replacement.closed
        await device.send("ping")

    asyncio.run(scenario())


def test_cancelled_command_closes_link_before_the_next_command():
    class Writer:
        closed = False
        def is_closing(self): return self.closed
        def close(self): self.closed = True
        def write(self, data): pass
        async def drain(self): pass

    async def scenario():
        entered = asyncio.Event()

        class Reader:
            async def readline(self):
                entered.set()
                await asyncio.Event().wait()

        device = Device()
        device._reader, device._writer = Reader(), Writer()
        job = asyncio.create_task(device.send("press"))
        await entered.wait()
        queued = asyncio.create_task(device.send("click"))
        await asyncio.sleep(0)  # the next command is already waiting for the lock
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert not device.connected
        with pytest.raises(DeviceError, match="not connected"):
            await asyncio.wait_for(queued, .5)

    asyncio.run(scenario())


class FakeSerialBoard:
    """A pyserial-like port with the SERIAL_LINK firmware behind it: boot noise first, then replies."""

    BOOT = b"ets Jun  8 2016 00:22:57\r\nrst:0x1 (POWERON_RESET),boot:0x13\r\n\nhello power-on 512\n"

    def __init__(self, boot_noise=BOOT, ignore_first_syncs=0):
        import threading
        self.port = "COM9"
        self._out = bytearray(boot_noise)
        self._cv = threading.Condition()
        self._ignore = ignore_first_syncs
        self.received = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self._out)

    def read(self, n=1):
        with self._cv:
            if not self._out and not self.closed:
                self._cv.wait(0.05)
            if self.closed:
                raise OSError("port closed")
            data, self._out[:] = bytes(self._out[:n]), self._out[n:]
            return data

    def write(self, data):
        with self._cv:
            for line in data.decode().split("\n"):
                line = line.strip()
                if not line:
                    continue
                self.received.append(line)
                if line == "sync":
                    if self._ignore:
                        self._ignore -= 1
                        continue
                    self._out += b"ok hello power-on 900\n"
                elif line == "bad":
                    self._out += b"err unknown command\n"
                else:
                    self._out += b"ok\n"
            self._cv.notify_all()

    def reset_input_buffer(self):
        pass

    def close(self):
        with self._cv:
            self.closed = True
            self._cv.notify_all()


def test_serial_link_skips_boot_noise_and_round_trips():
    from hidagent.device import SerialLink

    async def scenario():
        board = FakeSerialBoard()
        device = Device()
        link = SerialLink(board, asyncio.get_running_loop())
        assert (await device.attach_serial(link)).startswith("hello power-on")
        assert device.connected and device.links == 1
        await device.send("move 10 0")
        with pytest.raises(DeviceError, match="unknown command"):
            await device.send("bad")
        await device.send("ping")
        assert board.received[-3:] == ["move 10 0", "bad", "ping"]
        board.close()  # unplugged
        await asyncio.sleep(0.2)
        assert not device.connected
        with pytest.raises(DeviceError):
            await device.send("ping")

    asyncio.run(scenario())


def test_serial_sync_retries_while_board_boots_without_desyncing():
    from hidagent.device import SerialLink

    async def scenario():
        board = FakeSerialBoard(ignore_first_syncs=2)  # still booting for the first two tries
        device = Device()
        link = SerialLink(board, asyncio.get_running_loop())
        await device.attach_serial(link)
        await device.send("ping")  # must read its own "ok", not a stale sync reply
        board.close()

    asyncio.run(scenario())


def test_serial_without_reply_raises():
    from hidagent.device import SerialLink

    class Silent(FakeSerialBoard):
        def write(self, data):
            pass

    async def scenario():
        board = Silent()
        link = SerialLink(board, asyncio.get_running_loop())
        with pytest.raises(DeviceError, match="SERIAL_LINK"):
            await Device().attach_serial(link, attempts=2)
        board.close()

    asyncio.run(scenario())
