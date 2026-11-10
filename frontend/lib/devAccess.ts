/**
 * Development access (local testing only). See docs/DEV_ACCESS.md.
 *
 * OFF by default. True only under `next dev` (NODE_ENV === "development") AND NEXT_PUBLIC_DEV_ACCESS=true (scripts\\start-frontend.ps1 sets it from DEV_ACCESS in .env); production builds always get "false". The NODE_ENV test is a second, independent guard that lets the bundler drop the dev code
 * from production builds.
 */
// Each file that needs the flag repeats this exact expression inline (a bundler can only remove the dev code
// from production builds when the condition is written where it is used):
//   const DEV_ACCESS = process.env.NODE_ENV === "development" && process.env.NEXT_PUBLIC_DEV_ACCESS === "true";

export type ServiceState = "UP" | "DOWN";
export interface ServiceInfo {
  status: ServiceState;
  detail?: string;
  latencyMs?: number;
  users?: number;
  capabilities?: Record<string, boolean>;
}
export interface DevStatus {
  devAccess: { enabled: boolean; available?: boolean; user?: { email: string; role: string } | null; message?: string };
  services?: { java: ServiceInfo; postgres: ServiceInfo; python: ServiceInfo };
  checkedAt?: string;
}
