"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";

/**
 * Public route group layout — Auth-Gated.
 * Redirects unauthenticated visitors to /login to protect system services & telemetry.
 */
export default function PublicLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const { isAuthenticated } = useAuth();
    const router = useRouter();
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
    }, []);

    useEffect(() => {
        if (mounted && !isAuthenticated) {
            router.replace("/login");
        }
    }, [mounted, isAuthenticated, router]);

    // Loading state while verifying client authentication
    if (!mounted || !isAuthenticated) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-[var(--color-bg)]">
                <div className="flex flex-col items-center gap-3">
                    <div className="w-8 h-8 rounded-full border-2 border-[var(--color-primary)] border-t-transparent animate-spin" />
                    <span className="text-xs text-[var(--color-text-muted)] tracking-wide">
                        Verifying session...
                    </span>
                </div>
            </div>
        );
    }

    return <>{children}</>;
}
