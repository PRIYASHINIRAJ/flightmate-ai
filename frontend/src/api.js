// Set VITE_API_URL when deploying (e.g. on Vercel) to the backend's address.
export const API_BASE = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

// Each visitor gets their own conversation on the backend.
function getSessionId() {
  try {
    let id = localStorage.getItem("flightmate-session");

    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("flightmate-session", id);
    }

    return id;
  } catch {
    return SESSION_FALLBACK;
  }
}

const SESSION_FALLBACK = crypto.randomUUID();

export async function postJson(path, body) {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Session-Id": getSessionId(),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    throw new Error(`Server error: ${response.status}`);
  }

  return response.json();
}
