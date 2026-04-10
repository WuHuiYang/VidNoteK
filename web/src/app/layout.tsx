import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VidNoteK - Video to Learning Notes",
  description:
    "The ultimate video/blog to learning notes tool. Supports Bilibili, YouTube, Douyin, and 30+ platforms with 13 output templates.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-[var(--bg-primary)] text-[var(--text-primary)]">
        {children}
      </body>
    </html>
  );
}
