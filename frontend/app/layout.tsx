import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { PrefsProvider } from "@/lib/prefs";
import "./globals.css";

export const metadata: Metadata = {
  title: "Spatial Intelligence",
  description: "Object measurement, video-to-3D reconstruction and virtual tours",
  manifest: "/manifest.webmanifest",
};
export const viewport: Viewport = { themeColor: "#2563eb", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <PrefsProvider>{children}</PrefsProvider>
      </body>
    </html>
  );
}
