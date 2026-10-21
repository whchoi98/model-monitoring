import { afterEach, expect, test, vi } from "vitest";
import { chatStream, setToken } from "./api";

afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

function stream(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

test("anonymous chat streams text and keeps the server session for the next question", async () => {
  setToken(null);
  let request: RequestInit | undefined;
  vi.stubGlobal("fetch", async (_url: string, init: RequestInit) => {
    request = init;
    return stream(['event: delta\ndata: {"text":"Answer"}\n\nevent: final\ndata: {"ok":true,"session_id":"chat-example"}\n\n']);
  });
  const text: string[] = [];
  const sessions: string[] = [];
  chatStream({ message: "Hello" }, { onDelta: value => text.push(value), onFinal: value => sessions.push(value.session_id!) });
  await vi.waitFor(() => expect(sessions).toEqual(["chat-example"]));
  expect(text).toEqual(["Answer"]);
  expect(new Headers(request!.headers).has("Authorization")).toBe(false);
});

test("an interrupted chat preserves partial text and reports a retryable failure", async () => {
  vi.stubGlobal("fetch", async () => stream(['event: delta\ndata: {"text":"Partial"}\n\n']));
  const text: string[] = [];
  const errors: Error[] = [];
  chatStream({ message: "Hello" }, { onDelta: value => text.push(value), onError: value => errors.push(value) });
  await vi.waitFor(() => expect(errors).toHaveLength(1));
  expect(text).toEqual(["Partial"]);
  expect(errors[0].name).toBe("StreamInterruptedError");
});

test("a server error cannot be followed by an apparent successful completion", async () => {
  vi.stubGlobal("fetch", async () => stream([
    'event: error\ndata: {"message":"Unavailable"}\n\n',
    'event: final\ndata: {"ok":true}\n\n',
  ]));
  const errors: string[] = [];
  const finals: unknown[] = [];
  chatStream({ message: "Hello" }, { onError: value => errors.push(value.message), onFinal: value => finals.push(value) });
  await vi.waitFor(() => expect(errors).toEqual(["Unavailable"]));
  expect(finals).toEqual([]);
});

test("public usage limits return the service explanation instead of a bare HTTP code", async () => {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ detail: "Please wait before sending another question." }), { status: 429 }));
  const errors: string[] = [];
  chatStream({ message: "Hello" }, { onError: value => errors.push(value.message) });
  await vi.waitFor(() => expect(errors).toEqual(["Please wait before sending another question."]));
});
