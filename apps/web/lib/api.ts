import type { components } from "./api.generated";
export type Language = components["schemas"]["CallInput"]["language"];
export type User = components["schemas"]["UserOut"];
export type CallRecord = components["schemas"]["CallOut"];
export type Product = components["schemas"]["ProductOut"];
export type Refund = components["schemas"]["RefundOut"];
export type ReturnRecord = components["schemas"]["ReturnOut"];
export type Order = components["schemas"]["OrderOut"];
export type Ticket = components["schemas"]["TicketOut"];
export type Customer = components["schemas"]["CustomerOut"] & {
  name: string;
  email: string;
};
export type Action = components["schemas"]["ActionOut"];
export type Escalation = components["schemas"]["EscalationDetail"];
export type CallDetail = components["schemas"]["CallDetailOut"];
export type Connection = components["schemas"]["ConnectionOut"];
export type Portal = components["schemas"]["PortalOut"];
export type Dashboard = Omit<
  components["schemas"]["DashboardOut"],
  "customers"
> & { customers: Customer[] };
export type Analytics = {
  calls: number;
  metrics: Record<string, { count: number; mean: number; p95: number }>;
  handoffs: Record<string, number>;
};
let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown,
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "Service unavailable" }));
    throw new Error(
      typeof body.detail === "string"
        ? body.detail
        : "Please check the supplied values",
    );
  }
  return response.json();
}
export function money(paise: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);
}
export function date(ts: number) {
  return new Date(ts * 1000).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}
export function label(value: string) {
  return value.replaceAll("_", " ");
}
