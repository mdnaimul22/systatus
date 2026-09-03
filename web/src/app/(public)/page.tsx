"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { AppShell } from "@/components/layout/app-shell";
import { useAuth } from "@/hooks/use-auth";
import { systemApi, sudoApi, setSessionSudoPassword, clearSessionSudoPassword } from "@/lib/api";
import type {
    SystemOverview,
    ServiceStatus,
    ServiceAction,
    ServiceScope,
    StructuredLogEntry
} from "@/types/system";

export default function Dashboard() {
    const { isAuthenticated } = useAuth();

    // Telemetry & Services State
    const [overview, setOverview] = useState<SystemOverview | null>(null);
    const [services, setServices] = useState<ServiceStatus[]>([]);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
    const [actionLoading, setActionLoading] = useState<string | null>(null);

    // Filter State
    const [searchQuery, setSearchQuery] = useState("");
    const [scopeFilter, setScopeFilter] = useState<"all" | "user" | "system">("all");
    const [stateFilter, setStateFilter] = useState<"all" | "active" | "inactive" | "failed">("all");

    // Selected Service & Logs State
    const [selectedService, setSelectedService] = useState<ServiceStatus | null>(null);
    const [logs, setLogs] = useState<StructuredLogEntry[]>([]);
    const [logsLoading, setLogsLoading] = useState(false);
    const [logPriorityFilter, setLogPriorityFilter] = useState<string>("all");
    const [liveStreaming, setLiveStreaming] = useState(true);
    const [logGrep, setLogGrep] = useState("");
    const [logPriority, setLogPriority] = useState<number | undefined>(undefined);
    const [autoScroll, setAutoScroll] = useState(true);

    const logContainerRef = useRef<HTMLDivElement>(null);
    const eventSourceRef = useRef<EventSource | null>(null);

    // Unit File Editor State
    const [editorOpen, setEditorOpen] = useState(false);
    const [editorService, setEditorService] = useState<ServiceStatus | null>(null);
    const [editorContent, setEditorContent] = useState("");
    const [editorPath, setEditorPath] = useState("");
    const [editorWritable, setEditorWritable] = useState(true);
    const [editorLoading, setEditorLoading] = useState(false);
    const [editorSaving, setEditorSaving] = useState(false);
    const [editorRestart, setEditorRestart] = useState(false);

    // Delete Modal State
    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [deleteService, setDeleteService] = useState<ServiceStatus | null>(null);
    const [deleting, setDeleting] = useState(false);

    // Sudo Auth Modal State
    const [sudoModalOpen, setSudoModalOpen] = useState(false);
    const [sudoPasswordInput, setSudoPasswordInput] = useState("");
    const [sudoVerifying, setSudoVerifying] = useState(false);
    const [sudoError, setSudoError] = useState<string | null>(null);
    const [sudoShowPassword, setSudoShowPassword] = useState(false);
    const [sudoPendingAction, setSudoPendingAction] = useState<(() => Promise<void>) | null>(null);
    const [sudoStatus, setSudoStatus] = useState<{ nopasswd: boolean } | null>(null);

    // Toast Notification
    const [toast, setToast] = useState<{ text: string; type: "success" | "error" } | null>(null);

    const showToast = (text: string, type: "success" | "error" = "success") => {
        setToast({ text, type });
        setTimeout(() => setToast(null), 4000);
    };

    useEffect(() => {
        if (!isAuthenticated) return;
        sudoApi.getStatus().then(setSudoStatus).catch(() => null);
    }, [isAuthenticated]);

    const executePrivilegedOperation = async (operation: () => Promise<void>) => {
        try {
            await operation();
        } catch (err: unknown) {
            console.error("Privileged operation error:", err);
            const status = (err as { status?: number })?.status;
            const data = (err as { data?: { error?: string; detail?: string; message?: string } })?.data;
            const isSudoRequired =
                status === 403 &&
                (data?.error === "sudo_required" || (data?.detail && data.detail.includes("Root privileges")));
            const isInvalidPassword = status === 401 && data?.error === "invalid_password";

            if (isSudoRequired || isInvalidPassword) {
                setSudoPendingAction(() => operation);
                setSudoError(isInvalidPassword ? "Incorrect sudo password. Please try again." : null);
                setSudoPasswordInput("");
                setSudoModalOpen(true);
            } else {
                const msg = err instanceof Error ? err.message : "Operation failed";
                showToast(msg, "error");
            }
        }
    };

    const handleSudoSubmit = async (e?: React.FormEvent) => {
        if (e) e.preventDefault();
        if (!sudoPasswordInput.trim()) {
            setSudoError("Please enter your administrator password.");
            return;
        }

        setSudoVerifying(true);
        setSudoError(null);
        try {
            await sudoApi.verify(sudoPasswordInput);
            setSessionSudoPassword(sudoPasswordInput);
            setSudoModalOpen(false);
            showToast("Root credentials authenticated", "success");

            if (sudoPendingAction) {
                const action = sudoPendingAction;
                setSudoPendingAction(null);
                await action();
            }
        } catch (err: unknown) {
            console.error("Sudo authentication failed:", err);
            setSudoError("Authentication failed: Incorrect sudo password.");
            clearSessionSudoPassword();
        } finally {
            setSudoVerifying(false);
        }
    };

    const handleOpenEditor = async (service: ServiceStatus) => {
        setEditorService(service);
        setEditorOpen(true);
        setEditorLoading(true);
        try {
            const data = await systemApi.getFile(service.id, service.scope);
            setEditorContent(data.content);
            setEditorPath(data.path);
            setEditorWritable(data.is_writable);
        } catch (err: unknown) {
            console.error("Failed to load unit file", err);
            const msg = err instanceof Error ? err.message : "Failed to load unit file";
            showToast(msg, "error");
        } finally {
            setEditorLoading(false);
        }
    };

    const handleSaveEditor = async () => {
        if (!editorService) return;
        setEditorSaving(true);
        await executePrivilegedOperation(async () => {
            const res = await systemApi.updateFile(
                editorService.id,
                editorContent,
                editorService.scope,
                editorRestart
            );
            showToast(res.message, "success");
            setEditorOpen(false);
            await refreshData();
        });
        setEditorSaving(false);
    };

    const handleOpenDelete = (service: ServiceStatus) => {
        setDeleteService(service);
        setDeleteModalOpen(true);
    };

    const handleConfirmDelete = async () => {
        if (!deleteService) return;
        setDeleting(true);
        await executePrivilegedOperation(async () => {
            const res = await systemApi.deleteFile(deleteService.id, deleteService.scope);
            showToast(res.message, "success");
            setDeleteModalOpen(false);
            if (selectedService?.id === deleteService.id) {
                setSelectedService(null);
                setLogs([]);
            }
            await refreshData();
        });
        setDeleting(false);
    };

    // 1. Fetch Overview & Services
    const refreshData = useCallback(async () => {
        if (!isAuthenticated) return;
        try {
            const [overviewData, servicesData] = await Promise.all([
                systemApi.getOverview(),
                systemApi.getServices(),
            ]);
            setOverview(overviewData);
            setServices(servicesData);
            setLastUpdated(new Date());

            setSelectedService((prev) => {
                if (!prev && servicesData.length > 0) {
                    return servicesData.find(s => s.is_active) || servicesData[0];
                }
                if (prev) {
                    return servicesData.find(s => s.id === prev.id) || prev;
                }
                return null;
            });
        } catch (err) {
            console.error("Failed to fetch system data:", err);
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    // Initial load and periodic polling (every 5 seconds)
    useEffect(() => {
        if (!isAuthenticated) return;
        refreshData();
        const interval = setInterval(() => {
            refreshData();
        }, 5000);
        return () => clearInterval(interval);
    }, [isAuthenticated, refreshData]);

    // 2. Fetch Historical Logs when selected service changes
    const fetchLogs = useCallback(async (service: ServiceStatus) => {
        if (!isAuthenticated) return;
        setLogsLoading(true);
        try {
            const entries = await systemApi.getLogs(service.id, {
                lines: 100,
                priority: logPriority,
                grep: logGrep || undefined,
                scope: service.scope
            });
            setLogs(entries);
        } catch (err) {
            console.error("Failed to load logs:", err);
        } finally {
            setLogsLoading(false);
        }
    }, [isAuthenticated, logPriority, logGrep]);

    useEffect(() => {
        if (selectedService && !liveStreaming) {
            fetchLogs(selectedService);
        }
    }, [selectedService, liveStreaming, fetchLogs]);

    // 3. Real-Time SSE Log Streaming
    useEffect(() => {
        if (!isAuthenticated || !selectedService || !liveStreaming) {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
            return;
        }

        // Close previous SSE if open
        if (eventSourceRef.current) {
            eventSourceRef.current.close();
        }

        const streamUrl = systemApi.getStreamUrl(selectedService.id, 40, selectedService.scope);
        const es = new EventSource(streamUrl);
        eventSourceRef.current = es;

        es.onmessage = (event) => {
            try {
                const entry: StructuredLogEntry = JSON.parse(event.data);
                setLogs((prev) => {
                    // Filter duplicates if any
                    const exists = prev.some(
                        (item) => item.realtime_usec && item.realtime_usec === entry.realtime_usec
                    );
                    if (exists) return prev;
                    const updated = [...prev, entry];
                    return updated.length > 500 ? updated.slice(updated.length - 500) : updated;
                });
            } catch (e) {
                console.error("SSE parse error", e);
            }
        };

        es.onerror = () => {
            // Reconnect handled automatically by EventSource
        };

        return () => {
            es.close();
            eventSourceRef.current = null;
        };
    }, [selectedService, liveStreaming]);

    // Auto-scroll to bottom of log container
    useEffect(() => {
        if (autoScroll && logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
        }
    }, [logs, autoScroll]);

    // Service Action Trigger
    const handleServiceAction = async (service: ServiceStatus, action: ServiceAction) => {
        const key = `${service.id}-${action}`;
        setActionLoading(key);
        await executePrivilegedOperation(async () => {
            const res = await systemApi.executeAction(service.id, action, service.scope);
            showToast(res.message, "success");
            await refreshData();
        });
        setActionLoading(null);
    };

    // Filter services list
    const filteredServices = services.filter((s) => {
        const matchesQuery =
            s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            s.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
            s.description.toLowerCase().includes(searchQuery.toLowerCase());

        const matchesScope =
            scopeFilter === "all" ? true : s.scope === scopeFilter;

        const matchesState =
            stateFilter === "all"
                ? true
                : stateFilter === "active"
                ? s.is_active
                : stateFilter === "failed"
                ? s.is_failed
                : !s.is_active;

        return matchesQuery && matchesScope && matchesState;
    });

    // Formatting Helpers
    const formatUptime = (seconds: number) => {
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h}h ${m}m ${s}s`;
    };

    const formatBytes = (bytes: number | null | undefined) => {
        if (!bytes || bytes <= 0) return "0 B";
        const k = 1024;
        const dm = 1;
        const sizes = ["B", "KB", "MB", "GB", "TB"];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + " " + sizes[i];
    };

    const getPriorityBadge = (level: string) => {
        switch (level) {
            case "EMERGENCY":
            case "ALERT":
            case "CRITICAL":
            case "ERROR":
                return "text-red-600 dark:text-red-400 bg-red-500/15 border-red-500/30";
            case "WARNING":
                return "text-amber-600 dark:text-amber-400 bg-amber-500/15 border-amber-500/30";
            case "NOTICE":
            case "INFO":
                return "text-cyan-700 dark:text-cyan-400 bg-cyan-500/15 border-cyan-500/30";
            default:
                return "text-[var(--color-text-muted)] bg-[var(--color-surface)] border-[var(--color-border)]";
        }
    };

    return (
        <AppShell
            title="System Service Control"
            description="Root & User systemctl monitoring with structured journalctl live log stream"
            actions={
                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-xs text-[var(--color-text-secondary)]">
                        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                        <span>Daemon: 8686</span>
                    </div>
                    {sudoStatus && (
                        <div
                            className="flex items-center gap-2 px-3 py-1.5 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] text-xs text-[var(--color-text-secondary)] shadow-sm transition-all"
                            title={
                                sudoStatus.nopasswd
                                    ? "Passwordless root elevation active (NOPASSWD)"
                                    : "Root elevation requires password verification"
                            }
                        >
                            <span
                                className={`w-2 h-2 rounded-full ${
                                    sudoStatus.nopasswd
                                        ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]"
                                        : "bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.5)]"
                                }`}
                            ></span>
                            <span className="font-medium">
                                {sudoStatus.nopasswd ? "Root: NOPASSWD" : "Root: Sudo Auth"}
                            </span>
                        </div>
                    )}
                    <button
                        onClick={() => refreshData()}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] hover:bg-[var(--color-primary-light)] text-xs font-medium text-[var(--color-text)] transition-all cursor-pointer shadow-sm"
                        title="Manual Refresh"
                    >
                        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Refresh
                    </button>
                </div>
            }
        >
            <div className="space-y-6 max-w-[1600px] mx-auto">
                {/* ── 1. Telemetry & Host Overview Cards ─────────────────────────────────── */}
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    {/* Host & Uptime */}
                    <div className="p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] backdrop-blur-md shadow-sm transition-all hover:border-[var(--color-primary)]/40">
                        <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)] font-medium">
                            <span>HOST & UPTIME</span>
                            <span className="px-2 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-400 font-mono">
                                ONLINE
                            </span>
                        </div>
                        <div className="mt-2 flex items-baseline gap-2">
                            <h3 className="text-xl font-bold tracking-tight text-[var(--color-text)]">
                                {overview?.hostname || "localhost"}
                            </h3>
                        </div>
                        <p className="mt-1 text-xs text-[var(--color-text-secondary)] font-mono">
                            Up: {overview ? formatUptime(overview.uptime_seconds) : "..."}
                        </p>
                    </div>

                    {/* Monitored Services */}
                    <div className="p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] backdrop-blur-md shadow-sm transition-all hover:border-[var(--color-primary)]/40">
                        <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)] font-medium">
                            <span>SERVICES STATUS</span>
                            <span className="text-[10px] font-mono text-[var(--color-text-muted)]">
                                {overview?.total_services_monitored || 0} TOTAL
                            </span>
                        </div>
                        <div className="mt-2 flex items-center gap-3">
                            <div className="flex items-center gap-1.5">
                                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
                                <span className="text-xl font-bold text-[var(--color-text)]">
                                    {overview?.active_services || 0}
                                </span>
                                <span className="text-xs text-[var(--color-text-muted)]">Running</span>
                            </div>
                            <div className="flex items-center gap-1.5">
                                <span className="w-2.5 h-2.5 rounded-full bg-red-500"></span>
                                <span className="text-xl font-bold text-[var(--color-text)]">
                                    {overview?.failed_services || 0}
                                </span>
                                <span className="text-xs text-[var(--color-text-muted)]">Failed</span>
                            </div>
                        </div>
                        <p className="mt-1 text-xs text-[var(--color-text-secondary)] font-mono">
                            {overview?.inactive_services || 0} stopped / inactive
                        </p>
                    </div>

                    {/* Memory Usage */}
                    <div className="p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] backdrop-blur-md shadow-sm transition-all hover:border-[var(--color-primary)]/40">
                        <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)] font-medium">
                            <span>RAM ALLOCATION</span>
                            <span className="text-[10px] font-mono text-[var(--color-text-muted)]">
                                {overview
                                    ? `${Math.round(
                                          ((overview.memory_total_bytes - overview.memory_available_bytes) /
                                              overview.memory_total_bytes) *
                                              100
                                      )}%`
                                    : "0%"}
                            </span>
                        </div>
                        <div className="mt-2 flex items-baseline gap-1">
                            <span className="text-xl font-bold text-[var(--color-text)]">
                                {overview
                                    ? formatBytes(overview.memory_total_bytes - overview.memory_available_bytes)
                                    : "..."}
                            </span>
                            <span className="text-xs text-[var(--color-text-muted)]">
                                / {overview ? formatBytes(overview.memory_total_bytes) : "..."}
                            </span>
                        </div>
                        {/* Progress Bar */}
                        <div className="mt-2 w-full h-1.5 bg-[var(--color-border)] rounded-full overflow-hidden">
                            <div
                                className="h-full bg-[var(--color-primary,theme(colors.emerald.500))] rounded-full transition-all duration-500"
                                style={{
                                    width: overview
                                        ? `${Math.min(
                                              100,
                                              ((overview.memory_total_bytes - overview.memory_available_bytes) /
                                                  overview.memory_total_bytes) *
                                                  100
                                          )}%`
                                        : "0%",
                                }}
                            ></div>
                        </div>
                    </div>

                    {/* CPU & Load Average */}
                    <div className="p-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] backdrop-blur-md shadow-sm transition-all hover:border-[var(--color-primary)]/40">
                        <div className="flex items-center justify-between text-xs text-[var(--color-text-muted)] font-medium">
                            <span>CPU & LOAD AVG</span>
                            <span className="text-[10px] font-mono text-[var(--color-text-muted)]">
                                {overview?.cpu_count || 1} CORES
                            </span>
                        </div>
                        <div className="mt-2 flex items-baseline gap-2">
                            <h3 className="text-xl font-bold tracking-tight text-[var(--color-text)] font-mono">
                                {overview?.load_average?.[0]?.toFixed(2) || "0.00"}
                            </h3>
                            <span className="text-xs text-[var(--color-text-muted)]">1m load</span>
                        </div>
                        <p className="mt-1 text-xs text-[var(--color-text-secondary)] font-mono truncate">
                            5m: {overview?.load_average?.[1]?.toFixed(2) || "0.00"} | 15m:{" "}
                            {overview?.load_average?.[2]?.toFixed(2) || "0.00"}
                        </p>
                    </div>
                </div>

                {/* ── 2. Split Workspace (Services Explorer on Left, Live Log Console on Right) ─── */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
                    {/* LEFT PANEL: Service Explorer (5 Cols) */}
                    <div className="lg:col-span-5 flex flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-sm overflow-hidden">
                        {/* Panel Header & Filters */}
                        <div className="p-4 border-b border-[var(--color-border)] space-y-3 bg-[var(--color-surface-hover,var(--color-surface))]">
                            <div className="flex items-center justify-between">
                                <h2 className="text-sm font-semibold text-[var(--color-text)] flex items-center gap-2">
                                    <svg className="w-4 h-4 text-[var(--color-primary)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                    </svg>
                                    Custom Services ({filteredServices.length})
                                </h2>
                                <span className="text-[11px] text-[var(--color-text-muted)]">
                                    auto-polled 5s
                                </span>
                            </div>

                            {/* Search bar */}
                            <div className="relative">
                                <input
                                    type="text"
                                    placeholder="Filter by name, unit, keyword..."
                                    value={searchQuery}
                                    onChange={(e) => setSearchQuery(e.target.value)}
                                    className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] placeholder-[var(--color-text-muted)] focus:outline-none focus:border-[var(--color-primary)] transition-all"
                                />
                                <svg className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                                </svg>
                            </div>

                            {/* Scope & State Filters */}
                            <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                                <span className="text-[var(--color-text-muted)] font-medium mr-1">Scope:</span>
                                {(["all", "user", "system"] as const).map((sc) => (
                                    <button
                                        key={sc}
                                        onClick={() => setScopeFilter(sc)}
                                        className={`px-2 py-0.5 rounded capitalize transition-all cursor-pointer ${
                                            scopeFilter === sc
                                                ? "bg-[var(--color-primary)] text-white font-semibold"
                                                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-border)]"
                                        }`}
                                    >
                                        {sc}
                                    </button>
                                ))}

                                <span className="text-[var(--color-text-muted)] font-medium mx-1">| State:</span>
                                {(["all", "active", "inactive", "failed"] as const).map((st) => (
                                    <button
                                        key={st}
                                        onClick={() => setStateFilter(st)}
                                        className={`px-2 py-0.5 rounded capitalize transition-all cursor-pointer ${
                                            stateFilter === st
                                                ? "bg-[var(--color-primary)] text-white font-semibold"
                                                : "text-[var(--color-text-secondary)] hover:bg-[var(--color-border)]"
                                        }`}
                                    >
                                        {st}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Service Cards List */}
                        <div className="divide-y divide-[var(--color-border)] max-h-[640px] overflow-y-auto">
                            {loading && services.length === 0 ? (
                                <div className="p-8 text-center text-xs text-[var(--color-text-muted)]">
                                    Scanning systemctl services...
                                </div>
                            ) : filteredServices.length === 0 ? (
                                <div className="p-8 text-center text-xs text-[var(--color-text-muted)]">
                                    No services match the active filters.
                                </div>
                            ) : (
                                filteredServices.map((service) => {
                                    const isSelected = selectedService?.id === service.id;
                                    const isStarting = actionLoading === `${service.id}-start`;
                                    const isStopping = actionLoading === `${service.id}-stop`;
                                    const isRestarting = actionLoading === `${service.id}-restart`;

                                    return (
                                        <div
                                            key={`${service.id}-${service.scope}`}
                                            onClick={() => setSelectedService(service)}
                                            className={`p-3.5 transition-all cursor-pointer flex flex-col gap-2 ${
                                                isSelected
                                                    ? "bg-[var(--color-primary-light,theme(colors.slate.800))] border-l-4 border-l-[var(--color-primary)]"
                                                    : "hover:bg-[var(--color-border)]/20"
                                            }`}
                                        >
                                            <div className="flex items-start justify-between gap-2">
                                                <div className="flex items-center gap-2 min-w-0">
                                                    {/* Status indicator pulse */}
                                                    <span
                                                        className={`w-2.5 h-2.5 rounded-full shrink-0 ${
                                                            service.is_crash_loop
                                                                ? "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)] animate-ping"
                                                                : service.is_active
                                                                ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)] animate-pulse"
                                                                : service.is_failed
                                                                ? "bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.7)]"
                                                                : "bg-slate-500"
                                                        }`}
                                                    ></span>
                                                    <span className="font-semibold text-xs text-[var(--color-text)] truncate">
                                                        {service.name}
                                                    </span>
                                                </div>

                                                <div className="flex items-center gap-1.5 shrink-0">
                                                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono border border-[var(--color-border)] text-[var(--color-text-muted)] uppercase">
                                                        {service.scope}
                                                    </span>
                                                    <span
                                                        className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-medium ${
                                                            service.is_crash_loop
                                                                ? "text-amber-300 bg-amber-950/40 border border-amber-800/50 animate-pulse"
                                                                : service.is_active
                                                                ? "text-emerald-400 bg-emerald-950/30"
                                                                : service.is_failed
                                                                ? "text-red-400 bg-red-950/30 border border-red-900/40"
                                                                : "text-slate-400 bg-slate-800/30"
                                                        }`}
                                                    >
                                                        {service.is_crash_loop ? "crash-loop" : service.sub_state}
                                                    </span>
                                                </div>
                                            </div>

                                            {service.description && (
                                                <p className="text-[11px] text-[var(--color-text-secondary)] line-clamp-1">
                                                    {service.description}
                                                </p>
                                            )}

                                            <div className="flex items-center justify-between text-[11px] text-[var(--color-text-muted)] pt-1">
                                                <div className="flex items-center gap-3 font-mono text-[10px]">
                                                    {service.main_pid > 0 && (
                                                        <span>PID: {service.main_pid}</span>
                                                    )}
                                                    {service.memory_bytes && service.memory_bytes > 0 && (
                                                        <span>RAM: {formatBytes(service.memory_bytes)}</span>
                                                    )}
                                                </div>

                                                {/* Action Controls */}
                                                <div
                                                    className="flex items-center gap-1"
                                                    onClick={(e) => e.stopPropagation()}
                                                >
                                                    {(() => {
                                                        const canStop =
                                                            service.is_active ||
                                                            service.is_failed ||
                                                            service.is_crash_loop ||
                                                            service.active_state === "activating" ||
                                                            service.sub_state === "auto-restart";

                                                        return canStop ? (
                                                            <>
                                                                <button
                                                                    disabled={isRestarting}
                                                                    onClick={() =>
                                                                        handleServiceAction(service, "restart")
                                                                    }
                                                                    className="px-2 py-1 text-[10px] font-medium rounded border border-[var(--color-border)] hover:bg-[var(--color-primary-light)] text-[var(--color-text-secondary)] transition-all cursor-pointer disabled:opacity-50"
                                                                    title="Restart service"
                                                                >
                                                                    {isRestarting ? "..." : "🔄"}
                                                                </button>
                                                                <button
                                                                    disabled={isStopping}
                                                                    onClick={() =>
                                                                        handleServiceAction(service, "stop")
                                                                    }
                                                                    className="px-2 py-1 text-[10px] font-medium rounded border border-red-900/50 hover:bg-red-950/40 text-red-400 transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1"
                                                                    title="Stop service / abort crash loop"
                                                                >
                                                                    <span>{isStopping ? "..." : "⏹"}</span>
                                                                    {service.is_crash_loop && (
                                                                        <span className="text-[9px]">Stop Loop</span>
                                                                    )}
                                                                </button>
                                                            </>
                                                        ) : (
                                                            <button
                                                                disabled={isStarting}
                                                                onClick={() =>
                                                                    handleServiceAction(service, "start")
                                                                }
                                                                className="px-2 py-1 text-[10px] font-medium rounded border border-emerald-900/50 hover:bg-emerald-950/40 text-emerald-400 transition-all cursor-pointer disabled:opacity-50"
                                                                title="Start service"
                                                            >
                                                                {isStarting ? "..." : "▶ Start"}
                                                            </button>
                                                        );
                                                    })()}

                                                    {/* Unit File Editor Button */}
                                                    <button
                                                        onClick={() => handleOpenEditor(service)}
                                                        className="px-2 py-1 text-[10px] font-medium rounded border border-cyan-900/50 hover:bg-cyan-950/40 text-cyan-400 transition-all cursor-pointer"
                                                        title="View & Edit Unit File"
                                                    >
                                                        📝 Config
                                                    </button>

                                                    {/* Delete Service Button */}
                                                    <button
                                                        onClick={() => handleOpenDelete(service)}
                                                        className="px-2 py-1 text-[10px] font-medium rounded border border-red-900/50 hover:bg-red-950/60 text-red-400 transition-all cursor-pointer"
                                                        title="Delete Unit File"
                                                    >
                                                        🗑️
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>

                    {/* RIGHT PANEL: Live Structured Journal Terminal (7 Cols) */}
                    <div className="lg:col-span-7 flex flex-col rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] shadow-lg overflow-hidden">
                        {/* Terminal Header */}
                        <div className="p-4 border-b border-[var(--color-border)] space-y-3 bg-[var(--color-surface-hover,var(--color-surface))]">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                    <div className="w-3 h-3 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.7)]"></div>
                                    <h3 className="text-sm font-bold text-[var(--color-text)] font-mono">
                                        {selectedService?.id || "No service selected"}
                                    </h3>
                                    {selectedService && (
                                        <span className="px-1.5 py-0.5 text-[10px] uppercase font-mono rounded bg-[var(--color-primary-light)] text-[var(--color-primary)] font-semibold border border-[var(--color-primary)]/20">
                                            {selectedService.scope}
                                        </span>
                                    )}
                                </div>

                                {/* Live SSE Toggle */}
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setLiveStreaming(!liveStreaming)}
                                        className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all cursor-pointer ${
                                            liveStreaming
                                                ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 shadow-[0_0_12px_rgba(16,185,129,0.2)] font-semibold"
                                                : "border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                                        }`}
                                    >
                                        <span
                                            className={`w-2 h-2 rounded-full ${
                                                liveStreaming
                                                    ? "bg-emerald-500 animate-ping"
                                                    : "bg-[var(--color-text-muted)]"
                                            }`}
                                        ></span>
                                        {liveStreaming ? "LIVE TAIL" : "PAUSED"}
                                    </button>

                                    <button
                                        onClick={() => setAutoScroll(!autoScroll)}
                                        className={`px-2 py-1 text-[11px] rounded border transition-all cursor-pointer ${
                                            autoScroll
                                                ? "border-[var(--color-primary)] bg-[var(--color-primary-light)] text-[var(--color-primary)] font-semibold"
                                                : "border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                                        }`}
                                        title="Auto-scroll log console"
                                    >
                                        Auto-Scroll: {autoScroll ? "ON" : "OFF"}
                                    </button>

                                    <button
                                        onClick={() => setLogs([])}
                                        className="px-2 py-1 text-[11px] rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text-secondary)] hover:text-[var(--color-text)] hover:bg-[var(--color-primary-light)] transition-all cursor-pointer"
                                        title="Clear view"
                                    >
                                        Clear
                                    </button>
                                </div>
                            </div>

                            {/* Log Search & Priority Filters */}
                            <div className="flex flex-wrap items-center gap-2 text-xs">
                                <div className="relative flex-1 min-w-[200px]">
                                    <input
                                        type="text"
                                        placeholder="Search journal log text..."
                                        value={logGrep}
                                        onChange={(e) => setLogGrep(e.target.value)}
                                        className="w-full pl-7 pr-3 py-1 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] placeholder-[var(--color-text-muted)] font-mono focus:outline-none focus:border-[var(--color-primary)]"
                                    />
                                    <svg className="w-3 h-3 absolute left-2 top-2 text-[var(--color-text-muted)]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
                                        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                                    </svg>
                                </div>

                                <div className="flex items-center gap-1 text-[11px]">
                                    <span className="text-[var(--color-text-muted)]">Severity:</span>
                                    <select
                                        value={logPriority !== undefined ? logPriority : ""}
                                        onChange={(e) =>
                                            setLogPriority(
                                                e.target.value === "" ? undefined : Number(e.target.value)
                                            )
                                        }
                                        className="px-2 py-1 text-xs rounded border border-[var(--color-border)] bg-[var(--color-bg)] text-[var(--color-text)] font-mono focus:outline-none cursor-pointer"
                                    >
                                        <option value="">All Priorities</option>
                                        <option value="3">Errors Only (≤ 3)</option>
                                        <option value="4">Warnings & Errors (≤ 4)</option>
                                        <option value="6">Info & Above (≤ 6)</option>
                                        <option value="7">Debug & Above (≤ 7)</option>
                                    </select>
                                </div>
                            </div>
                        </div>

                        {/* Terminal Body with Theme-Agnostic Adaptive Design */}
                        <div
                            ref={logContainerRef}
                            className="p-4 bg-[var(--color-bg)] text-[var(--color-text)] font-mono text-xs h-[560px] overflow-y-auto space-y-1.5 select-text selection:bg-[var(--color-primary-light)] border-t border-[var(--color-border)] shadow-inner transition-colors"
                        >
                            {logsLoading && logs.length === 0 ? (
                                <div className="h-full flex items-center justify-center text-[var(--color-text-muted)] font-mono">
                                    Connecting to journalctl log stream...
                                </div>
                            ) : logs.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-[var(--color-text-muted)] gap-2">
                                    <svg className="w-8 h-8 opacity-40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 0 02-2V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 02 2z" />
                                    </svg>
                                    <span>No log lines captured yet for this unit.</span>
                                </div>
                            ) : (
                                logs
                                    .filter((entry) => {
                                        if (!logGrep) return true;
                                        return entry.message.toLowerCase().includes(logGrep.toLowerCase());
                                    })
                                    .map((entry, idx) => {
                                        const timeStr = entry.timestamp
                                            ? entry.timestamp.substring(11, 23)
                                            : "--:--:--.---";

                                        return (
                                            <div
                                                key={entry.realtime_usec || idx}
                                                className="flex items-start gap-2 hover:bg-[var(--color-primary-light)]/60 py-0.5 px-1.5 rounded transition-colors group"
                                            >
                                                {/* Timestamp */}
                                                <span className="text-[var(--color-text-muted)] text-[11px] font-mono shrink-0 select-none opacity-80">
                                                    {timeStr}
                                                </span>

                                                {/* Level Tag */}
                                                <span
                                                    className={`px-1 py-0.2 rounded text-[9px] border font-bold shrink-0 select-none ${getPriorityBadge(
                                                        entry.level
                                                    )}`}
                                                >
                                                    {entry.level.slice(0, 4)}
                                                </span>

                                                {/* Identifier / PID */}
                                                {entry.syslog_identifier && (
                                                    <span className="text-[var(--color-primary)] text-[11px] font-semibold shrink-0 select-none opacity-90">
                                                        [{entry.syslog_identifier}
                                                        {entry.pid ? `:${entry.pid}` : ""}]
                                                    </span>
                                                )}

                                                {/* Message */}
                                                <span className="text-[var(--color-text)] break-all flex-1 whitespace-pre-wrap leading-relaxed font-mono">
                                                    {entry.message}
                                                </span>
                                            </div>
                                        );
                                    })
                            )}
                        </div>

                        {/* Terminal Footer Info */}
                        <div className="px-4 py-2 bg-[var(--color-surface)] border-t border-[var(--color-border)] flex items-center justify-between text-[11px] text-[var(--color-text-muted)] font-mono transition-colors">
                            <span>
                                Displaying {logs.length} entries &bull; Unit: {selectedService?.id}
                            </span>
                            <span className="flex items-center gap-1.5">
                                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                                Live SSE connected to :8686
                            </span>
                        </div>
                    </div>
                </div>

                {/* TOAST NOTIFICATION */}
                {toast && (
                    <div
                        className={`fixed bottom-6 right-6 z-50 px-4 py-2.5 rounded-xl border text-xs font-medium shadow-2xl backdrop-blur-md flex items-center gap-2.5 transition-all ${
                            toast.type === "success"
                                ? "bg-emerald-950/90 border-emerald-500/50 text-emerald-200"
                                : "bg-red-950/90 border-red-500/50 text-red-200"
                        }`}
                    >
                        <span>{toast.type === "success" ? "✓" : "⚠"}</span>
                        <span>{toast.text}</span>
                    </div>
                )}

                {/* UNIT FILE EDITOR MODAL */}
                {editorOpen && (
                    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
                        <div className="w-full max-w-4xl bg-[#090d16] border border-slate-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
                            {/* Header */}
                            <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-[#0e1320]">
                                <div className="flex items-center gap-3">
                                    <span className="p-2 rounded-lg bg-cyan-950/60 text-cyan-400 border border-cyan-800/50">
                                        📝
                                    </span>
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <h3 className="text-sm font-semibold text-white">
                                                {editorService?.id}
                                            </h3>
                                            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono border border-slate-700 text-slate-300 uppercase">
                                                {editorService?.scope}
                                            </span>
                                            <span
                                                className={`px-2 py-0.5 rounded text-[10px] font-mono font-medium ${
                                                    editorWritable
                                                        ? "text-emerald-400 bg-emerald-950/40 border border-emerald-800/40"
                                                        : "text-amber-400 bg-amber-950/40 border border-amber-800/40"
                                                }`}
                                            >
                                                {editorWritable ? "Writable" : "Root Protected (Uses Sudo)"}
                                            </span>
                                        </div>
                                        <p className="text-[11px] text-slate-400 font-mono truncate max-w-xl">
                                            {editorPath}
                                        </p>
                                    </div>
                                </div>
                                <button
                                    onClick={() => setEditorOpen(false)}
                                    className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-all cursor-pointer"
                                >
                                    ✕
                                </button>
                            </div>

                            {/* Body */}
                            <div className="p-4 flex-1 overflow-hidden flex flex-col bg-[#05070d]">
                                {editorLoading ? (
                                    <div className="flex-1 flex items-center justify-center p-12 text-xs text-slate-400">
                                        Loading unit file content...
                                    </div>
                                ) : (
                                    <textarea
                                        value={editorContent}
                                        onChange={(e) => setEditorContent(e.target.value)}
                                        className="w-full h-full min-h-[380px] p-4 font-mono text-xs text-emerald-300 bg-[#070a12] border border-slate-800 rounded-xl focus:outline-none focus:border-cyan-500/50 resize-none selection:bg-cyan-900/50 leading-relaxed"
                                        placeholder="Systemd configuration..."
                                        spellCheck={false}
                                    />
                                )}
                            </div>

                            {/* Footer */}
                            <div className="p-4 border-t border-slate-800 flex items-center justify-between bg-[#0e1320]">
                                <label className="flex items-center gap-2 text-xs text-slate-300 select-none cursor-pointer">
                                    <input
                                        type="checkbox"
                                        checked={editorRestart}
                                        onChange={(e) => setEditorRestart(e.target.checked)}
                                        className="rounded border-slate-700 bg-slate-800 text-cyan-500 focus:ring-0"
                                    />
                                    <span>Automatically restart service after reload</span>
                                </label>

                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setEditorOpen(false)}
                                        className="px-3 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 transition-all cursor-pointer"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        disabled={editorSaving || editorLoading}
                                        onClick={handleSaveEditor}
                                        className="px-4 py-1.5 text-xs font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition-all shadow-lg shadow-cyan-900/30 cursor-pointer disabled:opacity-50 flex items-center gap-2"
                                    >
                                        {editorSaving ? "Saving..." : "Save & Reload Systemd"}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}

                {/* DELETE SERVICE MODAL */}
                {deleteModalOpen && (
                    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
                        <div className="w-full max-w-md bg-[#090d16] border border-red-900/50 rounded-2xl shadow-2xl p-6 flex flex-col gap-4">
                            <div className="flex items-center gap-3 text-red-400">
                                <span className="p-2 rounded-xl bg-red-950/60 border border-red-800/50 text-lg">
                                    ⚠️
                                </span>
                                <div>
                                    <h3 className="text-sm font-bold text-white">
                                        Delete Service Unit
                                    </h3>
                                    <p className="text-xs text-slate-400">
                                        Permanent removal of systemd configuration
                                    </p>
                                </div>
                            </div>

                            <div className="p-3.5 rounded-xl bg-red-950/30 border border-red-900/40 text-xs text-red-200 leading-relaxed">
                                Are you sure you want to delete <strong className="font-mono text-white">{deleteService?.id}</strong>?
                                <div className="mt-2 text-[11px] text-slate-400 font-mono break-all">
                                    Target file: {deleteService?.unit_file_path}
                                </div>
                                <div className="mt-2 text-[11px] text-amber-300">
                                    &bull; The service will be immediately stopped and disabled.<br/>
                                    &bull; The unit file will be removed from disk.<br/>
                                    &bull; Systemd daemon will reload and clear state cache.
                                </div>
                            </div>

                            <div className="flex items-center justify-end gap-2 pt-2">
                                <button
                                    onClick={() => setDeleteModalOpen(false)}
                                    className="px-3.5 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 transition-all cursor-pointer"
                                >
                                    Cancel
                                </button>
                                <button
                                    disabled={deleting}
                                    onClick={handleConfirmDelete}
                                    className="px-4 py-1.5 text-xs font-semibold rounded-lg bg-red-600 hover:bg-red-500 text-white transition-all shadow-lg shadow-red-900/40 cursor-pointer disabled:opacity-50 flex items-center gap-2"
                                >
                                    {deleting ? "Deleting..." : "Confirm & Delete Service"}
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* SUDO AUTHENTICATION MODAL */}
                {sudoModalOpen && (
                    <div className="fixed inset-0 z-[70] bg-black/85 backdrop-blur-md flex items-center justify-center p-4">
                        <div className="w-full max-w-md bg-[#090d16] border border-amber-500/40 rounded-2xl shadow-2xl shadow-amber-950/30 p-6 flex flex-col gap-4">
                            <div className="flex items-center gap-3">
                                <span className="p-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xl text-amber-400">
                                    🔐
                                </span>
                                <div>
                                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                        Root Elevation Required
                                    </h3>
                                    <p className="text-xs text-slate-400">
                                        Administrator privilege is required for system units
                                    </p>
                                </div>
                            </div>

                            <p className="text-xs text-slate-300 leading-relaxed">
                                Managing system-level services in <code className="px-1 py-0.5 rounded bg-slate-800 text-amber-300 font-mono text-[11px]">/etc/systemd/system</code> requires root authorization. Please enter your administrator (sudo) password to proceed.
                            </p>

                            {sudoError && (
                                <div className="p-3 rounded-xl bg-red-950/40 border border-red-800/60 text-xs text-red-300 flex items-center gap-2">
                                    <span>⚠️</span>
                                    <span>{sudoError}</span>
                                </div>
                            )}

                            <form onSubmit={handleSudoSubmit} className="flex flex-col gap-3">
                                <div className="flex flex-col gap-1.5">
                                    <label className="text-[11px] font-semibold text-slate-300">
                                        SUDO PASSWORD
                                    </label>
                                    <div className="relative">
                                        <input
                                            autoFocus
                                            type={sudoShowPassword ? "text" : "password"}
                                            value={sudoPasswordInput}
                                            onChange={(e) => {
                                                setSudoPasswordInput(e.target.value);
                                                if (sudoError) setSudoError(null);
                                            }}
                                            placeholder="Enter system user password..."
                                            className="w-full px-3.5 py-2 rounded-xl bg-[#0d131f] border border-slate-700 focus:border-amber-500 focus:ring-1 focus:ring-amber-500 outline-none text-xs text-white placeholder-slate-500 pr-10 font-mono"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setSudoShowPassword(!sudoShowPassword)}
                                            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 text-xs cursor-pointer"
                                            tabIndex={-1}
                                        >
                                            {sudoShowPassword ? "👁️‍🗨️" : "👁️"}
                                        </button>
                                    </div>
                                    <span className="text-[10px] text-slate-500">
                                        Password is kept in runtime memory only and transmitted via loopback.
                                    </span>
                                </div>

                                <div className="flex items-center justify-end gap-2 pt-2">
                                    <button
                                        type="button"
                                        onClick={() => {
                                            setSudoModalOpen(false);
                                            setSudoPendingAction(null);
                                            setSudoError(null);
                                            setSudoPasswordInput("");
                                        }}
                                        className="px-3.5 py-1.5 text-xs rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800 transition-all cursor-pointer"
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        type="submit"
                                        disabled={sudoVerifying || !sudoPasswordInput.trim()}
                                        className="px-4 py-1.5 text-xs font-semibold rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition-all shadow-lg shadow-amber-900/30 cursor-pointer disabled:opacity-50 flex items-center gap-2"
                                    >
                                        {sudoVerifying ? (
                                            <>
                                                <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                                </svg>
                                                <span>Verifying...</span>
                                            </>
                                        ) : (
                                            <span>Authenticate & Proceed</span>
                                        )}
                                    </button>
                                </div>
                            </form>
                        </div>
                    </div>
                )}
            </div>
        </AppShell>
    );
}
