export async function request<T>(url: string, body?: unknown): Promise<T> {
  const response = await fetch(
    url,
    body === undefined
      ? undefined
      : {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
