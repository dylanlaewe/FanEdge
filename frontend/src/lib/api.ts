export async function request<T>(url: string, body?: unknown): Promise<T> {
  let session = "";
  if (typeof window !== "undefined") {
    session = sessionStorage.getItem("fanedge-session") || crypto.randomUUID();
    sessionStorage.setItem("fanedge-session", session);
  }
  const response = await fetch(
    url,
    body === undefined
      ? {
          headers: { "X-FanEdge-Session": session },
          signal: AbortSignal.timeout(60_000),
        }
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-FanEdge-Session": session,
          },
          signal: AbortSignal.timeout(60_000),
          body: JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : "FanEdge could not complete this request. Please try again.",
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export const title = (value: string) =>
  value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
