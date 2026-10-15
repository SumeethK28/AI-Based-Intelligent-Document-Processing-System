export type RecordData = Record<string, any>;
export type Session = {
  id: number;
  username: string;
  role: string;
  departments: string[];
  permissions: string[];
};
export async function api<T = RecordData>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/api" + path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    headers:
      body instanceof FormData
        ? { "X-IDP-Request": "1" }
        : { "Content-Type": "application/json", "X-IDP-Request": "1" },
    body:
      body === undefined
        ? undefined
        : body instanceof FormData
          ? body
          : JSON.stringify(body),
  });
  if (!response.ok) {
    const error = await response
      .json()
      .catch(() => ({ detail: "The service is unavailable. Try again." }));
    if (response.status === 401)
      window.dispatchEvent(new Event("idp-session-ended"));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Check the supplied fields and try again.",
    );
  }
  return response.json();
}
export async function download(
  kind: string,
  resource: RecordData,
  preview = false,
) {
  const { grant } = await api("/downloads", { kind, resource });
  const response = await fetch("/api/downloads/" + encodeURIComponent(grant), {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-IDP-Request": "1" },
  });
  if (!response.ok)
    throw new Error(
      "Download expired or unavailable. Request a fresh download.",
    );
  const blob = await response.blob(),
    url = URL.createObjectURL(blob);
  if (preview) return url;
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = decodeURIComponent(
    response.headers.get("content-disposition")?.split("UTF-8''")[1] ??
      "document.json",
  );
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return "";
}
