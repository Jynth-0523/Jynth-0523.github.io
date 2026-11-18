import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "127.0.0.1:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("127.") || host.startsWith("localhost") ? "http" : "https");
  const image = `${protocol}://${host}/platform-preview.png`;

  return {
    title: "Factor Discovery — Automatic Factor Research",
    description: "Upload a daily, weekly, monthly, or quarterly asset panel and discover, validate, and export factor candidates privately in your browser.",
    icons: { icon: "/favicon.svg", shortcut: "/favicon.svg" },
    openGraph: {
      title: "Factor Discovery — Automatic Factor Research",
      description: "Bring your data. Generate, screen, de-correlate, select, validate, and export factors without uploading observations.",
      type: "website",
      images: [{ url: image, width: 1733, height: 908, alt: "Private browser factor discovery workspace" }],
    },
    twitter: {
      card: "summary_large_image",
      title: "Factor Discovery — Automatic Factor Research",
      description: "Bring your data. Generate, screen, de-correlate, select, validate, and export factors without uploading observations.",
      images: [image],
    },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
