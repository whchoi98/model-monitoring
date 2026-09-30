"""가짜 Bedrock runtime — 로컬 소켓에서 converse와 converse-stream에 답한다(인사이트 Bedrock 테스트 공용).

실제 boto3 client가 AWS_ENDPOINT_URL_BEDROCK_RUNTIME으로 이 서버에 붙는다. 그래서 요청 서명, botocore 재시도, 소켓
read timeout, event stream 파싱, stream_watchdog의 소켓 shutdown이 운영과 같은 코드로 돈다. pytest가 모으지 않는
공용 모듈이다(파일 이름이 test_로 시작하지 않는다). 네트워크 밖으로 나가지 않는다(127.0.0.1).

요청은 system 프롬프트로 언어를 가른다("한국어"가 있으면 ko, 아니면 en). 언어마다 scripts[lang]에 넣어 둔 동작을 요청
순서대로 하나씩 꺼내 쓰고, 비어 있으면 default를 쓴다.

동작:
- Stream: 응답 헤더를 보낸 뒤 텍스트 델타를 gap_s 간격으로 보낸다(= 생성 중인 모델). stall_after가 있으면 그만큼 보낸 뒤
  연결을 연 채로 멈춘다(청크 사이 read timeout). messageStop, metadata로 끝난다.
- Silent: 요청을 읽고 헤더를 보내지 않는다(헤더 대기 read timeout).
- Blocking: 비스트림 /converse 응답 — delay_s 뒤에 본문 전체를 한 번에 보낸다(생성이 끝나야 첫 바이트가 오는 converse).
"""

from __future__ import annotations

import json
import socket
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Optional


def _header(name: str, value: str) -> bytes:
    n, v = name.encode(), value.encode()
    return struct.pack("!B", len(n)) + n + b"\x07" + struct.pack("!H", len(v)) + v  # 7 = string


def encode_event(event_type: str, payload: dict) -> bytes:
    """AWS event stream 메시지 하나(prelude + CRC, 헤더, JSON 본문, 메시지 CRC)."""
    headers = (_header(":event-type", event_type) + _header(":content-type", "application/json")
               + _header(":message-type", "event"))
    body = json.dumps(payload).encode()
    prelude = struct.pack("!II", 16 + len(headers) + len(body), len(headers))
    head = prelude + struct.pack("!I", zlib.crc32(prelude) & 0xFFFFFFFF) + headers + body
    return head + struct.pack("!I", zlib.crc32(head) & 0xFFFFFFFF)


@dataclass
class Stream:
    deltas: list[str]
    gap_s: float = 0.0
    stop_reason: str = "end_turn"
    input_tokens: int = 1500
    output_tokens: int = 321
    stall_after: Optional[int] = None


@dataclass
class Silent:
    pass


@dataclass
class Blocking:
    text: str
    delay_s: float


@dataclass
class Request:
    path: str
    lang: str
    body: dict
    started: float
    finished: Optional[float] = None
    outcome: str = "open"  # completed | stalled | silent | aborted
    sent_deltas: int = 0


@dataclass
class FakeBedrock:
    default: object = field(default_factory=lambda: Stream(["기본 요약"]))
    scripts: dict = field(default_factory=lambda: {"ko": [], "en": []})
    requests: list = field(default_factory=list)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._conns: list[socket.socket] = []
        self._closing = threading.Event()
        self._srv = socket.socket()
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(16)
        self.url = f"http://127.0.0.1:{self._srv.getsockname()[1]}"
        threading.Thread(target=self._accept, daemon=True).start()

    # ── 조회 ──
    def by_lang(self, lang: str) -> list[Request]:
        with self._lock:
            return [r for r in self.requests if r.lang == lang]

    def paths(self) -> list[str]:
        with self._lock:
            return [r.path for r in self.requests]

    # ── 서버 ──
    def close(self) -> None:
        self._closing.set()
        try:
            self._srv.close()
        except OSError:
            pass
        with self._lock:
            conns = list(self._conns)
        for c in conns:
            try:
                c.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            c.close()

    def _accept(self) -> None:
        while not self._closing.is_set():
            try:
                conn, _ = self._srv.accept()
            except OSError:
                return
            with self._lock:
                self._conns.append(conn)
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    @staticmethod
    def _read_request(conn: socket.socket) -> tuple[str, dict]:
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = conn.recv(65536)
            if not chunk:
                raise ConnectionError("client closed")
            buf += chunk
        head, rest = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        path = lines[0].split(" ")[1]
        length = 0
        for line in lines[1:]:
            name, _, value = line.partition(":")
            if name.strip().lower() == "content-length":
                length = int(value.strip())
        while len(rest) < length:
            chunk = conn.recv(65536)
            if not chunk:
                raise ConnectionError("client closed")
            rest += chunk
        return path, json.loads(rest[:length] or b"{}")

    def _serve(self, conn: socket.socket) -> None:
        try:
            path, body = self._read_request(conn)
        except (OSError, ValueError):
            conn.close()
            return
        system = "".join(part.get("text", "") for part in body.get("system", []))
        lang = "ko" if "한국어" in system else "en"
        req = Request(path=path, lang=lang, body=body, started=time.monotonic())
        with self._lock:
            self.requests.append(req)
            queue = self.scripts.setdefault(lang, [])
            behaviour = queue.pop(0) if queue else self.default
        try:
            if isinstance(behaviour, Silent) or (isinstance(behaviour, Stream) and path.endswith("/converse")):
                req.outcome = "silent"
                self._closing.wait(3600)
            elif isinstance(behaviour, Blocking) or path.endswith("/converse"):
                self._blocking(conn, req, behaviour if isinstance(behaviour, Blocking) else Blocking("요약", 0.0))
            else:
                self._stream(conn, req, behaviour)
        except OSError:
            req.outcome = "aborted"  # 클라이언트가 소켓을 끊었다(watchdog, read timeout)
        finally:
            req.finished = time.monotonic()
            conn.close()

    def _blocking(self, conn: socket.socket, req: Request, b: Blocking) -> None:
        if self._closing.wait(b.delay_s):
            return
        payload = json.dumps({
            "output": {"message": {"role": "assistant", "content": [{"text": b.text}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
            "metrics": {"latencyMs": int(b.delay_s * 1000)},
        }).encode()
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n"
                     + f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
        req.outcome = "completed"

    def _stream(self, conn: socket.socket, req: Request, s: Stream) -> None:
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/vnd.amazon.eventstream\r\n"
                     b"Transfer-Encoding: chunked\r\nConnection: close\r\nx-amzn-RequestId: fake\r\n\r\n")

        def send(event_type: str, payload: dict) -> None:
            msg = encode_event(event_type, payload)
            conn.sendall(f"{len(msg):x}\r\n".encode() + msg + b"\r\n")

        send("messageStart", {"role": "assistant"})
        for i, text in enumerate(s.deltas):
            if s.stall_after is not None and i >= s.stall_after:
                req.outcome = "stalled"
                self._closing.wait(3600)
                return
            if s.gap_s and self._closing.wait(s.gap_s):
                return
            send("contentBlockDelta", {"delta": {"text": text}, "contentBlockIndex": 0})
            req.sent_deltas += 1
        send("contentBlockStop", {"contentBlockIndex": 0})
        send("messageStop", {"stopReason": s.stop_reason})
        send("metadata", {"usage": {"inputTokens": s.input_tokens, "outputTokens": s.output_tokens,
                                    "totalTokens": s.input_tokens + s.output_tokens},
                          "metrics": {"latencyMs": 1234}})
        conn.sendall(b"0\r\n\r\n")
        req.outcome = "completed"
