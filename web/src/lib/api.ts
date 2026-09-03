/**
 * Secure FastAPI API client.
 *
 * Security measures:
 * - All responses are validated (non-2xx throws)
 * - Content-Type is enforced
 * - JWT Bearer auth from Zustand store
 * - Request timeout prevents hanging connections
 * - No eval() or innerHTML — JSON.parse only
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8686";
const REQUEST_TIMEOUT_MS = 30_000;

/** Custom API error with status code and response body */
export class ApiError extends Error {
    constructor(
        public readonly status: number,
        public readonly statusText: string,
        public readonly body: unknown,
    ) {
        super(`API Error ${status}: ${statusText}`);
        this.name = "ApiError";
    }

    /** Extract a human-readable error string from FastAPI responses. */
    getDetail(): string {
        const b = this.body as Record<string, unknown> | null;
        if (!b) return this.statusText;
        const errorVal = b.error || b.detail;
        if (typeof errorVal === "string") return errorVal;
        // Pydantic 422: detail is [{type, loc, msg, input, ctx}, ...]
        if (Array.isArray(errorVal) && errorVal.length > 0) {
            const first = errorVal[0];
            if (typeof first === "object" && first !== null && "msg" in first) {
                return String((first as Record<string, unknown>).msg);
            }
            return String(first);
        }
        return this.statusText;
    }
}

/**
 * Get auth token from localStorage (Zustand persist store).
 * Avoids circular dependency with hooks.
 */
function getToken(): string | null {
    try {
        const raw = localStorage.getItem("app-auth");
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        return parsed?.state?.token ?? null;
    } catch {
        return null;
    }
}

let inMemorySudoPassword: string | null = null;

export function getSessionSudoPassword(): string | null {
    if (inMemorySudoPassword) return inMemorySudoPassword;
    if (typeof window !== "undefined") {
        return sessionStorage.getItem("sys_sudo_pwd");
    }
    return null;
}

export function setSessionSudoPassword(password: string | null) {
    inMemorySudoPassword = password;
    if (typeof window !== "undefined") {
        if (password) {
            sessionStorage.setItem("sys_sudo_pwd", password);
        } else {
            sessionStorage.removeItem("sys_sudo_pwd");
        }
    }
}

export function clearSessionSudoPassword() {
    setSessionSudoPassword(null);
}

/**
 * Type-safe fetch wrapper for FastAPI backend.
 *
 * @example
 *   const users = await apiFetch<User[]>("/api/users");
 *   const user  = await apiFetch<User>("/api/users", { method: "POST", body: JSON.stringify(data) });
 */
export async function apiFetch<T>(
    endpoint: string,
    options?: RequestInit,
): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

    const token = getToken();
    const headers: Record<string, string> = {
        "Content-Type": "application/json",
        ...(options?.headers as Record<string, string>),
    };
    if (token) {
        headers["Authorization"] = `Bearer ${token}`;
    }

    const sudoPwd = getSessionSudoPassword();
    if (sudoPwd && !headers["X-Sudo-Password"]) {
        headers["X-Sudo-Password"] = sudoPwd;
    }

    try {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            headers,
            signal: controller.signal,
            ...options,
        });

        if (!res.ok) {
            const body = await res.json().catch(() => null);
            if (res.status === 401 && !endpoint.includes("/api/auth/login")) {
                try {
                    localStorage.removeItem("app-auth");
                    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
                        window.location.href = "/login";
                    }
                } catch {}
            }
            throw new ApiError(res.status, res.statusText, body);
        }

        return (await res.json()) as T;
    } finally {
        clearTimeout(timeout);
    }
}

/**
 * Convenience methods matching FastAPI router patterns.
 */
export const api = {
    get: <T>(endpoint: string) => apiFetch<T>(endpoint),

    post: <T>(endpoint: string, data: unknown) =>
        apiFetch<T>(endpoint, {
            method: "POST",
            body: JSON.stringify(data),
        }),

    put: <T>(endpoint: string, data: unknown) =>
        apiFetch<T>(endpoint, {
            method: "PUT",
            body: JSON.stringify(data),
        }),

    patch: <T>(endpoint: string, data: unknown) =>
        apiFetch<T>(endpoint, {
            method: "PATCH",
            body: JSON.stringify(data),
        }),

    delete: <T>(endpoint: string) =>
        apiFetch<T>(endpoint, { method: "DELETE" }),
} as const;

import type {
    SystemOverview,
    ServiceStatus,
    ServiceAction,
    ServiceScope,
    ServiceActionResponse,
    ServiceFileContent,
    ServiceFileOperationResponse,
    StructuredLogEntry
} from "@/types/system";

export const systemApi = {
    getOverview: () => apiFetch<SystemOverview>("/api/system/overview"),
    getServices: () => apiFetch<ServiceStatus[]>("/api/services"),
    getService: (id: string, scope?: ServiceScope) =>
        apiFetch<ServiceStatus>(`/api/services/${id}${scope ? `?scope=${scope}` : ""}`),
    executeAction: (id: string, action: ServiceAction, scope: ServiceScope = "system") =>
        apiFetch<ServiceActionResponse>(`/api/services/${id}/action`, {
            method: "POST",
            body: JSON.stringify({ action, scope }),
        }),
    getLogs: (
        id: string,
        params?: { lines?: number; priority?: number; grep?: string; scope?: ServiceScope }
    ) => {
        const query = new URLSearchParams();
        if (params?.lines) query.set("lines", String(params.lines));
        if (params?.priority !== undefined) query.set("priority", String(params.priority));
        if (params?.grep) query.set("grep", params.grep);
        if (params?.scope) query.set("scope", params.scope);
        const qStr = query.toString();
        return apiFetch<StructuredLogEntry[]>(`/api/services/${id}/logs${qStr ? `?${qStr}` : ""}`);
    },
    getStreamUrl: (id: string, initialLines = 30, scope?: ServiceScope) => {
        const query = new URLSearchParams({ initial_lines: String(initialLines) });
        if (scope) query.set("scope", scope);
        const token = getToken();
        if (token) query.set("token", token);
        return `${API_BASE}/api/services/${id}/logs/stream?${query.toString()}`;
    },
    getFile: (id: string, scope?: ServiceScope) =>
        apiFetch<ServiceFileContent>(`/api/services/${id}/file${scope ? `?scope=${scope}` : ""}`),
    updateFile: (id: string, content: string, scope?: ServiceScope, restartAfterUpdate = false) =>
        apiFetch<ServiceFileOperationResponse>(`/api/services/${id}/file`, {
            method: "PUT",
            body: JSON.stringify({ content, scope, restart_after_update: restartAfterUpdate }),
        }),
    deleteFile: (id: string, scope?: ServiceScope) =>
        apiFetch<ServiceFileOperationResponse>(`/api/services/${id}/file${scope ? `?scope=${scope}` : ""}`, {
            method: "DELETE",
        }),
};

export const sudoApi = {
    getStatus: () => apiFetch<{ nopasswd: boolean }>("/api/auth/sudo-status"),
    verify: (password: string) =>
        apiFetch<{ valid: boolean; message: string }>("/api/auth/sudo-verify", {
            method: "POST",
            body: JSON.stringify({ sudo_password: password }),
        }),
};
