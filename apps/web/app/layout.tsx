import type { Metadata } from "next";
import "@livekit/components-styles";
import "./globals.css";
export const metadata: Metadata = {
  title: "Northstar · Voice support",
  description:
    "Customer support that listens. Real-time voice assistance powered by LiveKit and Gemini.",
};
export default function Layout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
