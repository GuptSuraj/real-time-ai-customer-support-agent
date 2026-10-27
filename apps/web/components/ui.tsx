import type { ReactNode } from "react";
import { label } from "@/lib/api";
export function Badge({ status }: { status: string }) {
  return (
    <span
      className={`badge ${["delivered", "completed", "resolved", "active", "received"].includes(status) ? "green" : ["failed", "rejected", "cancelled"].includes(status) ? "red" : ""}`}
    >
      {label(status)}
    </span>
  );
}
export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
export function SectionTitle({
  eyebrow,
  title,
  children,
}: {
  eyebrow?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2>{title}</h2>
      </div>
      {children}
    </div>
  );
}
