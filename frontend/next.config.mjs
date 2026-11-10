import { PHASE_DEVELOPMENT_SERVER } from "next/constants.js";

// Development access (local testing only, see docs/DEV_ACCESS.md).
// The bypass is on by default while running `next dev` (set DEV_ACCESS=false to turn it off); `next build` / `next start` always get "false",
// so a production build cannot contain it, whatever DEV_ACCESS is set to.
export default function config(phase) {
  const devAccess = phase === PHASE_DEVELOPMENT_SERVER && process.env.DEV_ACCESS !== "false";
  /** @type {import('next').NextConfig} */
  return {
    reactStrictMode: true,
    transpilePackages: ["three"],
    env: { NEXT_PUBLIC_DEV_ACCESS: devAccess ? "true" : "false" },
  };
}
