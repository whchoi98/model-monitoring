import { afterEach, describe, expect, test, vi } from "vitest";
import { getToken, runProbe, setToken } from "./api";

const config = { model_ids: ["a"], prompt: "probe", temperature: 0, max_tokens: 10, concurrency: 1, repeat_count: 1 };

afterEach(() => { vi.unstubAllGlobals(); setToken(null); });

function response(chunks: string[]) {
  const encoder = new TextEncoder();
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }), { headers: { "Content-Type": "text/event-stream" } });
}

describe("manual probe stream completion", () => {
  test("a verified 401 clears the rejected session so the shared sign-in gate can recover", async () => {
    setToken("expired-token");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    const errors: Error[] = [];
    runProbe(config, { onError: (error) => errors.push(error) });
    await vi.waitFor(() => expect(errors).toHaveLength(1));
    expect(getToken()).toBeNull();
  });

  test("an older request's rejection never signs out a newer login", async () => {
    setToken("expired-token");
    let rejectOld!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((resolve) => { rejectOld = resolve; })));
    const errors: Error[] = [];
    runProbe(config, { onError: (error) => errors.push(error) });
    setToken("fresh-token");
    rejectOld(new Response("{}", { status: 401 }));
    await vi.waitFor(() => expect(errors).toHaveLength(1));
    expect(getToken()).toBe("fresh-token");
  });

  test("an interrupted stream reports failure instead of leaving the run active forever", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(['event: token\ndata: {"token":"partial"}\n\n'])));
    const errors: Error[] = [];
    runProbe(config, { onError: (error) => errors.push(error) });
    await vi.waitFor(() => expect(errors).toHaveLength(1));
    expect(errors[0].name).toBe("StreamInterruptedError");
  });

  test("server error events are visible and do not become an apparent successful completion", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response(['event: error\ndata: {"message":"Probe failed"}\n\n'])));
    const errors: string[] = [];
    let completed = false;
    runProbe(config, { onError: (error) => errors.push(error.message), onComplete: () => { completed = true; } });
    await vi.waitFor(() => expect(errors).toEqual(["Probe failed"]));
    expect(completed).toBe(false);
  });

  test("handles a frame split across CRLF chunks and completes exactly once", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response([
      'event: token\r\ndata: {"token":"한글"}\r',
      '\n\r\nevent: complete\r\ndata: {"run_id":7,"total":1}\r\n\r\n',
      'event: complete\ndata: {"run_id":7,"total":1}\n\n',
    ])));
    const tokens: string[] = [];
    const runs: number[] = [];
    const errors: Error[] = [];
    runProbe(config, {
      onToken: (data) => tokens.push(data.token),
      onComplete: (data) => runs.push(data.run_id),
      onError: (error) => errors.push(error),
    });
    await vi.waitFor(() => expect(runs).toEqual([7]));
    expect(tokens).toEqual(["한글"]);
    expect(errors).toEqual([]);
  });
});
