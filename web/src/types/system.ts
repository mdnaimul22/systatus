export type ServiceScope = "system" | "user";

export type ServiceAction = "start" | "stop" | "restart" | "reload";

export interface ServiceStatus {
    id: string;
    name: string;
    description: string;
    load_state: string;
    active_state: string;
    sub_state: string;
    unit_file_state: string | null;
    main_pid: number;
    memory_bytes: number | null;
    cpu_usage_nsec: number | null;
    scope: ServiceScope;
    is_active: boolean;
    is_failed: boolean;
    is_crash_loop: boolean;
    unit_file_path: string | null;
}

export interface ServiceActionResponse {
    success: boolean;
    service_id: string;
    action: string;
    message: string;
    details?: string;
}

export interface StructuredLogEntry {
    timestamp: string | null;
    realtime_usec: number | null;
    priority: number;
    level: string;
    unit: string | null;
    syslog_identifier: string | null;
    pid: number | null;
    message: string;
    raw?: Record<string, unknown>;
}

export interface SystemOverview {
    hostname: string;
    uptime_seconds: number;
    total_services_monitored: number;
    active_services: number;
    failed_services: number;
    inactive_services: number;
    memory_total_bytes: number;
    memory_available_bytes: number;
    cpu_count: number;
    load_average: number[];
}

export interface ServiceFileContent {
    unit_name: string;
    path: string;
    content: string;
    is_writable: boolean;
}

export interface ServiceFileOperationResponse {
    success: boolean;
    unit_name: string;
    message: string;
    path?: string;
}
