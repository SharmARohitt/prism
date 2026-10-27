import type { Metadata } from "next";
import "./globals.css";
import { AppBackground } from "@/components/AppBackground";
import { Navbar } from "@/components/Navbar";

export const metadata: Metadata = {
  title: "PRISM — Persistent Repository Intelligence & Security Mapping",
  description: "Understand the change. Explain the risk. Prove the review.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-[#07090c] text-foreground antialiased">
        {/* Full-screen ASCII gradient background — visible on all inner pages */}
        <AppBackground />
        <div className="relative z-10">
          <Navbar />
          <main className="relative">{children}</main>
        </div>
      </body>
    </html>
  );
}
