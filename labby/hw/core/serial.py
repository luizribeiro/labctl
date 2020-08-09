import fcntl
import queue
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

from serial import Serial


class SerialDevice(ABC):
    WAIT_TIME_AFTER_WRITE_MS: float = 0.0

    serial_controller: "SerialController"

    def __init__(self, port: str, baudrate: int) -> None:
        self.serial_controller = SerialController.get_or_create(
            port, baudrate, self.WAIT_TIME_AFTER_WRITE_MS
        )

    def _write(self, msg: bytes) -> None:
        self.serial_controller.write(msg)

    def _query(self, msg: bytes) -> str:
        return self.serial_controller.query(msg)

    def open(self) -> None:
        if not self.serial_controller.is_alive():
            self.serial_controller.start()
        self._on_open()

    def close(self) -> None:
        self.serial_controller.close()

    @abstractmethod
    def _on_open(self) -> None:
        pass


TIMEOUT_MS = 2000


REGISTRY_LOCK = threading.Lock()
SERIAL_CONTROLLERS: Dict[str, "SerialController"] = {}


class SerialControllerJobType(Enum):
    WRITE = 0
    QUERY = 1
    CLOSE = 2


@dataclass
class SerialControllerJob:
    condition: threading.Condition = field(init=False)
    uuid: str = field(init=False)
    type: SerialControllerJobType
    message: bytes = b""

    def __post_init__(self) -> None:
        self.condition = threading.Condition()
        self.uuid = str(uuid.uuid4())


class SerialController(threading.Thread):
    serial: Serial
    job_queue: "queue.Queue[SerialControllerJob]"
    job_results: Dict[str, str]
    num_clients: int
    wait_time_after_write_ms: float

    def __init__(
        self, port: str, baudrate: int, wait_time_after_write_ms: float
    ) -> None:
        super().__init__()
        self.daemon = True

        self.serial = Serial()
        self.serial.port = port
        self.serial.baudrate = baudrate
        self.serial.xonxoff = True
        self.serial.timeout = TIMEOUT_MS / 1000.0

        self.wait_time_after_write_ms = wait_time_after_write_ms

        self.job_queue = queue.Queue()
        self.job_results = {}
        self.num_clients = 0

    @classmethod
    def get_or_create(
        cls, port: str, baudrate: int, wait_time_after_write_ms: float = 0.0
    ) -> "SerialController":
        with REGISTRY_LOCK:
            if (
                port in SERIAL_CONTROLLERS.keys()
                and SERIAL_CONTROLLERS[port].is_alive()
            ):
                return SERIAL_CONTROLLERS[port]
            serial_controller = SerialController(
                port, baudrate, wait_time_after_write_ms
            )
            serial_controller.num_clients += 1
            SERIAL_CONTROLLERS[port] = serial_controller
            return serial_controller

    def _run_and_wait(self, job: SerialControllerJob) -> None:
        with job.condition:
            self.job_queue.put(job)
            job.condition.wait()

    def write(self, message: bytes) -> None:
        job = SerialControllerJob(type=SerialControllerJobType.WRITE, message=message)
        self._run_and_wait(job)

    def query(self, message: bytes) -> str:
        job = SerialControllerJob(type=SerialControllerJobType.QUERY, message=message)
        self._run_and_wait(job)

        result = self.job_results[job.uuid]
        del self.job_results[job.uuid]
        return result

    def close(self) -> None:
        job = SerialControllerJob(type=SerialControllerJobType.CLOSE)
        self._run_and_wait(job)

    def _write(self, message: bytes) -> None:
        self.serial.write(message)
        time.sleep(self.wait_time_after_write_ms / 1000.0)

    def _execute_job(self, job: SerialControllerJob) -> None:
        if job.type == SerialControllerJobType.WRITE:
            self._write(job.message)
            return

        if job.type == SerialControllerJobType.QUERY:
            self._write(job.message)
            response = self.serial.readline()[:-2].decode("utf-8")
            self.job_results[job.uuid] = response
            return

        if job.type == SerialControllerJobType.CLOSE:
            with REGISTRY_LOCK:
                self.num_clients -= 1
                if self.num_clients == 0:
                    del SERIAL_CONTROLLERS[self.serial.port]
            return

    def run(self) -> None:
        try:
            self.serial.open()
            fcntl.flock(self.serial, fcntl.LOCK_EX | fcntl.LOCK_NB)

            while self.serial.port in SERIAL_CONTROLLERS.keys():
                job = self.job_queue.get()
                with job.condition:
                    self._execute_job(job)
                    job.condition.notify()
                self.job_queue.task_done()

            assert self.job_queue.empty()

        finally:
            self.serial.close()