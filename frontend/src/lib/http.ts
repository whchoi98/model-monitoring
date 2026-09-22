/** Structured errors let the UI distinguish authentication, service failure and empty data. */
export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function fetchJson<T>(url: string, init: RequestInit = {}, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  if (init.signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  init.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new ApiError(response.status, typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
    }
    try {
      return await response.json() as T;
    } catch (error) {
      if (controller.signal.aborted) throw error;
      throw new ApiError(response.status, "Invalid JSON response");
    }
  } catch (error) {
    if (timedOut) throw new DOMException("Request timed out", "TimeoutError");
    throw error;
  } finally {
    clearTimeout(timeout);
    init.signal?.removeEventListener("abort", abort);
  }
}
