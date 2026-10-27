"use client";
import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import {
  ArrowUpRight,
  ArrowRight,
  AudioLines,
  Check,
  ChevronRight,
  ClipboardList,
  Clock3,
  Headphones,
  LogOut,
  MessageSquareText,
  Package,
  Phone,
  ShieldCheck,
  Sparkles,
  Star,
  Users,
  X,
  Activity,
  RefreshCw,
} from "lucide-react";
import {
  api,
  date,
  label,
  money,
  setCsrf,
  type Analytics,
  type CallDetail,
  type Connection,
  type Customer,
  type Dashboard,
  type Language,
  type Order,
  type Portal,
  type Ticket,
  type User,
} from "@/lib/api";
import { Badge, Empty, SectionTitle } from "@/components/ui";
const VoiceRoom = dynamic(() => import("@/components/voice-room"), {
  ssr: false,
  loading: () => <p className="muted">Preparing audio…</p>,
});
type Tab =
  | "overview"
  | "orders"
  | "tickets"
  | "customers"
  | "calls"
  | "analytics";

export default function Home() {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview"),
    [portal, setPortal] = useState<Portal | null>(null),
    [dashboard, setDashboard] = useState<Dashboard | null>(null),
    [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null),
    [detail, setDetail] = useState<CallDetail | null>(null),
    [reviewId, setReviewId] = useState<string | null>(null);
  const [language, setLanguage] = useState<Language>("en"),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null),
    [customerOrders, setCustomerOrders] = useState<Order[]>([]);
  const activeCallId = connection?.call.id || reviewId;
  const refresh = useCallback(async () => {
    if (!user) return;
    if (user.role === "customer") setPortal(await api<Portal>("/portal"));
    else {
      const [d, a] = await Promise.all([
        api<Dashboard>("/staff/dashboard"),
        api<Analytics>("/staff/analytics"),
      ]);
      setDashboard(d);
      setAnalytics(a);
    }
    if (activeCallId)
      setDetail(await api<CallDetail>(`/calls/${activeCallId}`));
  }, [user, activeCallId]);
  useEffect(() => {
    api<{ user: User; csrf: string }>("/auth/me")
      .then((d) => {
        setCsrf(d.csrf);
        setUser(d.user);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (!user) return;
    refresh().catch((e) => setError(e.message));
    const events = new EventSource("/api/events");
    events.addEventListener("refresh", () => refresh().catch(() => {}));
    events.addEventListener("session_expired", () => {
      setUser(null);
      events.close();
    });
    events.onopen = () => refresh().catch(() => {});
    const poll = setInterval(() => refresh().catch(() => {}), 5000);
    return () => {
      events.close();
      clearInterval(poll);
    };
  }, [user, refresh]);
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function startCall() {
    await run(async () => {
      const c = await api<Connection>("/calls", "POST", { language });
      setConnection(c);
      setReviewId(null);
      setDetail(null);
    });
  }
  async function endCall() {
    if (!connection) return;
    await run(async () => {
      if (user?.role === "customer")
        await api(`/calls/${connection.call.id}/end`, "POST", {});
      setReviewId(connection.call.id);
      setConnection(null);
      setNotice(
        user?.role === "staff"
          ? "You left the room. Use Reconnect to rejoin this handoff."
          : "Call ended. Your transcript and requests are saved.",
      );
    });
  }
  async function logout() {
    if (connection && user?.role === "customer")
      await api(`/calls/${connection.call.id}/end`, "POST", {});
    await api("/auth/logout", "POST", {});
    setConnection(null);
    setPortal(null);
    setDashboard(null);
    setUser(null);
    setCsrf("");
    setTab("overview");
  }
  const login = async (email: string, password: string) => {
    const d = await api<{ user: User; csrf: string }>("/auth/login", "POST", {
      email,
      password,
    });
    setCsrf(d.csrf);
    setUser(d.user);
    setError("");
  };
  if (loading)
    return (
      <div className="loading-screen">
        <div className="brand-mark">
          <AudioLines />
        </div>
        <p>Opening Northstar…</p>
      </div>
    );
  if (!user) return <Login onLogin={login} />;
  const staff = user.role === "staff";
  const tabs: { id: Tab; title: string; icon: typeof Package }[] = staff
    ? [
        { id: "overview", title: "Workspace", icon: Activity },
        { id: "tickets", title: "Tickets & approvals", icon: ClipboardList },
        { id: "customers", title: "Customers", icon: Users },
        { id: "calls", title: "Call history", icon: Phone },
        { id: "analytics", title: "Analytics", icon: Activity },
      ]
    : [
        { id: "overview", title: "Overview", icon: Sparkles },
        { id: "orders", title: "My orders", icon: Package },
        { id: "tickets", title: "Support tickets", icon: MessageSquareText },
      ];
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-mark">
            <AudioLines size={22} />
          </span>
          northstar<span className="brand-period">.</span>
        </a>
        <div className="workspace-label">
          {staff ? "SUPPORT WORKSPACE" : "CUSTOMER PORTAL"}
        </div>
        <nav aria-label="Main navigation">
          {tabs.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "nav-item selected" : "nav-item"}
              onClick={() => setTab(t.id)}
            >
              <t.icon size={18} />
              {t.title}
              {t.id === "tickets" && (
                <span className="nav-count">
                  {staff
                    ? dashboard?.tickets.filter((t) => t.status !== "resolved")
                        .length || 0
                    : portal?.tickets.length || 0}
                </span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <div className="small-icon">
            <ShieldCheck size={19} />
          </div>
          <strong>A little help, always here.</strong>
          <p>
            {staff
              ? "Resolve the details. Keep the human connection."
              : "Real answers, for everything after checkout."}
          </p>
        </div>
        <button
          className="profile"
          onClick={() => logout().catch((e) => setError(e.message))}
        >
          <span className="avatar">{user.name[0]}</span>
          <span>
            <strong>{user.name.split(" ·")[0]}</strong>
            <small>
              {staff ? "Support representative" : "Customer account"}
            </small>
          </span>
          <LogOut size={16} />
        </button>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            <span className="muted">{staff ? "Support" : "Your account"}</span>
            <ChevronRight size={14} />
            {tabs.find((t) => t.id === tab)?.title}
          </span>
          <div className="topbar-right">
            <span className="live-indicator">
              <i />
              {connection ? "Call in progress" : "Support is online"}
            </span>
            <span className="top-avatar">{user.name[0]}</span>
          </div>
        </header>
        <main>
          {error && (
            <div className="alert error" role="alert">
              {error}
              <button aria-label="Dismiss error" onClick={() => setError("")}>
                <X size={16} />
              </button>
            </div>
          )}
          {notice && (
            <div className="alert success" role="status">
              {notice}
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          <div className="page-heading">
            <div>
              <p className="eyebrow">
                {staff ? "THE SUPPORT DESK" : "A GOOD DAY TO GET THINGS SORTED"}
              </p>
              <h1>
                {staff
                  ? "Make someone’s day easier."
                  : `Hello, ${user.name.split(" ")[0]}.`}
                <span className="heading-dot">✳</span>
              </h1>
              <p className="muted">
                {staff
                  ? "Your queue, customer context, and a human touch—all in one place."
                  : "Your orders, your questions. We’re here for all of it."}
              </p>
            </div>
            <span className="date-pill">
              {new Date().toLocaleDateString("en-IN", {
                weekday: "short",
                day: "numeric",
                month: "short",
              })}
            </span>
          </div>
          {!staff && tab === "overview" && (
            <>
              <div className="customer-grid">
                <section className="hero-card">
                  <div className="hero-content">
                    <span className="hero-chip">
                      <span className="status-dot live" /> MEET YOUR VOICE
                      ASSISTANT
                    </span>
                    <h2>
                      Let’s talk it
                      <br />
                      through.
                    </h2>
                    <p>
                      Orders, returns, or a refund that’s taking its time.
                      <br className="desktop" /> Just ask Mira. No hold music
                      required.
                    </p>
                    <div className="hero-actions">
                      <button
                        className="primary"
                        disabled={busy || !!connection}
                        onClick={startCall}
                      >
                        <Phone size={17} />
                        {busy ? "Connecting…" : "Talk to Mira"}
                        <ArrowUpRight size={16} />
                      </button>
                      <select
                        aria-label="Conversation language"
                        value={language}
                        onChange={(e) =>
                          setLanguage(e.target.value as Language)
                        }
                      >
                        <option value="en">English</option>
                        <option value="hi">हिन्दी</option>
                      </select>
                    </div>
                    <div className="hero-foot">
                      <ShieldCheck size={14} /> Private to your account{" "}
                      <span>·</span> English & हिन्दी
                    </div>
                  </div>
                  <div className="orb-scene" aria-hidden="true">
                    <div className="orbit orbit-one" />
                    <div className="orbit orbit-two" />
                    <div className="hero-orb">
                      <div className="wave-bars">
                        {[20, 38, 55, 31, 62, 44, 23].map((h, i) => (
                          <i key={i} style={{ height: h }} />
                        ))}
                      </div>
                    </div>
                    <span className="orb-caption">
                      <AudioLines size={13} /> A conversation, not a menu.
                    </span>
                  </div>
                </section>
                <section className="quick-card">
                  <span className="small-icon">
                    <MessageSquareText size={21} />
                  </span>
                  <h3>
                    A few things
                    <br />
                    Mira can help with.
                  </h3>
                  {[
                    { title: "Where’s my order?", icon: Package },
                    { title: "Start a return", icon: RefreshCw },
                    { title: "Check my refund", icon: Clock3 },
                  ].map((q) => (
                    <button
                      disabled={!!connection || busy}
                      className="quick-link"
                      key={q.title}
                      onClick={startCall}
                    >
                      <q.icon size={16} />
                      {q.title}
                      <ArrowRight size={15} />
                    </button>
                  ))}
                  <p className="small muted">
                    Need a person? Ask Mira to connect you.
                  </p>
                </section>
              </div>
              <div className="stat-row">
                <Stat
                  icon={Package}
                  title="Your orders"
                  value={portal?.orders.length || 0}
                  caption="Everything in one place"
                />
                <Stat
                  icon={RefreshCw}
                  title="Active requests"
                  value={
                    portal?.orders.filter((o) => o.return || o.refund).length ||
                    0
                  }
                  caption="Returns & refunds"
                />
                <Stat
                  icon={MessageSquareText}
                  title="Open tickets"
                  value={
                    portal?.tickets.filter((t) => t.status !== "resolved")
                      .length || 0
                  }
                  caption="We’re working on it"
                />
              </div>
              <SectionTitle eyebrow="AFTER CHECKOUT" title="Your recent orders">
                <button
                  className="text-button"
                  onClick={() => setTab("orders")}
                >
                  View all orders <ArrowRight size={15} />
                </button>
              </SectionTitle>
              <OrderTable orders={portal?.orders.slice(0, 3) || []} />
              <div className="bottom-note">
                <Star size={15} />
                <span>
                  Good support starts with listening. You’re in the right place.
                </span>
              </div>
            </>
          )}
          {!staff && tab === "orders" && (
            <>
              <SectionTitle title="My orders">
                <button
                  className="primary"
                  disabled={busy || !!connection}
                  onClick={startCall}
                >
                  <Headphones size={17} /> Ask about an order
                </button>
              </SectionTitle>
              <OrderTable orders={portal?.orders || []} expanded />
            </>
          )}
          {!staff && tab === "tickets" && (
            <>
              <SectionTitle title="Your support tickets" />
              <div className="ticket-grid">
                {portal?.tickets.map((t) => (
                  <TicketCard key={t.id} ticket={t} />
                ))}
                {!portal?.tickets.length && (
                  <Empty>
                    No tickets yet. Talk to Mira when you need a hand.
                  </Empty>
                )}
              </div>
              <SectionTitle title="Recent conversations" />
              <CallTable
                calls={portal?.calls || []}
                onReview={setReviewId}
                onEnd={(id) =>
                  run(async () => {
                    await api(`/calls/${id}/end`, "POST", {});
                  })
                }
              />
            </>
          )}
          {staff && tab === "overview" && dashboard && (
            <>
              <div className="stat-row">
                <Stat
                  icon={Headphones}
                  title="Waiting for a person"
                  value={
                    dashboard.escalations.filter((e) =>
                      ["queued", "claimed", "connecting"].includes(e.status),
                    ).length
                  }
                  caption="Live escalation queue"
                />
                <Stat
                  icon={ClipboardList}
                  title="Refund approvals"
                  value={
                    dashboard.refunds.filter(
                      (r) => r.status === "pending_approval",
                    ).length
                  }
                  caption="Your decision is required"
                />
                <Stat
                  icon={Phone}
                  title="Conversations"
                  value={dashboard.calls.length}
                  caption="Latest 100 calls"
                />
              </div>
              <SectionTitle
                eyebrow="MAKE THE CONNECTION"
                title="Live escalation queue"
              />
              <div className="escalation-grid">
                {dashboard.escalations
                  .filter((e) => !["completed", "cancelled"].includes(e.status))
                  .map((e) => (
                    <section className="card escalation" key={e.id}>
                      <div className="card-top">
                        <span className="avatar">{e.customer.name[0]}</span>
                        <div>
                          <h3>{e.customer.name}</h3>
                          <span className="small muted">
                            {e.verified
                              ? "Identity verified"
                              : "Identity not yet verified"}
                          </span>
                        </div>
                        <Badge status={e.status} />
                      </div>
                      <p>{e.reason}</p>
                      <p className="small muted">
                        {e.call.summary || "No summary yet"}
                      </p>
                      <div className="small muted">
                        {
                          e.actions.filter((a) => a.status === "completed")
                            .length
                        }{" "}
                        completed actions ·{" "}
                        {date(e.created_at || e.call.created_at)}
                      </div>
                      <div className="card-actions">
                        <button
                          className="text-button"
                          onClick={() => setReviewId(e.call_id)}
                        >
                          View context <ArrowRight size={14} />
                        </button>
                        {e.status === "queued" ? (
                          <button
                            className="primary"
                            disabled={busy}
                            onClick={() =>
                              run(async () => {
                                await api(
                                  `/staff/escalations/${e.id}/claim`,
                                  "POST",
                                  {},
                                );
                              })
                            }
                          >
                            Accept
                          </button>
                        ) : ["claimed", "connecting", "active"].includes(
                            e.status,
                          ) && e.assigned_to === user.id ? (
                          <button
                            className="primary"
                            disabled={busy || !!connection}
                            onClick={() =>
                              run(async () => {
                                setConnection(
                                  await api<Connection>(
                                    `/staff/escalations/${e.id}/join`,
                                    "POST",
                                    {},
                                  ),
                                );
                                setReviewId(null);
                              })
                            }
                          >
                            {e.status === "active" ? "Reconnect" : "Join call"}
                          </button>
                        ) : null}
                      </div>
                    </section>
                  ))}
                {!dashboard.escalations.some(
                  (e) => !["completed", "cancelled"].includes(e.status),
                ) && (
                  <Empty>
                    <Headphones size={28} />
                    <h3>A quiet moment.</h3>No customers are waiting for a
                    representative.
                  </Empty>
                )}
              </div>
              <SectionTitle title="Needs a decision" />
              <Refunds dashboard={dashboard} busy={busy} run={run} />
            </>
          )}
          {staff && tab === "tickets" && dashboard && (
            <>
              <SectionTitle title="Refund approvals" />
              <Refunds dashboard={dashboard} busy={busy} run={run} />
              <SectionTitle title="Return inspection" />
              <div className="card">
                {dashboard.returns.map((r) => (
                  <div className="list-row" key={r.id}>
                    <div>
                      <strong>{r.order_id}</strong>
                      <p className="muted small">{r.reason}</p>
                    </div>
                    <Badge status={r.status} />
                    {r.status !== "received" && (
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() =>
                          run(async () => {
                            await api(
                              `/staff/returns/${r.id}/receive`,
                              "POST",
                              {},
                            );
                          })
                        }
                      >
                        Mark received
                      </button>
                    )}
                  </div>
                ))}
              </div>
              <SectionTitle title="Support tickets" />
              <div className="ticket-grid">
                {dashboard.tickets.map((t) => (
                  <TicketCard
                    key={t.id}
                    ticket={t}
                    onSave={(status, notes) =>
                      run(async () => {
                        await api(`/staff/tickets/${t.id}`, "PATCH", {
                          status,
                          notes,
                          assign_to_me: true,
                        });
                      })
                    }
                  />
                ))}
              </div>
            </>
          )}
          {staff && tab === "customers" && dashboard && (
            <>
              <SectionTitle title="Customer records" />
              <div className="ticket-grid">
                {dashboard.customers.map((c) => (
                  <button
                    className="card customer-card"
                    key={c.id}
                    onClick={() =>
                      run(async () => {
                        const d = await api<{ orders: Order[] }>(
                          `/staff/customers/${c.id}`,
                        );
                        setCustomer(c);
                        setCustomerOrders(d.orders);
                      })
                    }
                  >
                    <span className="avatar">{c.name[0]}</span>
                    <h3>{c.name}</h3>
                    <p className="muted">{c.email}</p>
                    <span className="text-button">
                      View profile <ArrowRight size={15} />
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
          {staff && tab === "calls" && (
            <>
              <SectionTitle title="Conversation history" />
              <CallTable
                calls={dashboard?.calls || []}
                onReview={setReviewId}
              />
            </>
          )}
          {staff && tab === "analytics" && (
            <>
              <SectionTitle title="Call analytics" />
              <div className="stat-row">
                <Stat
                  icon={Phone}
                  title="Total calls"
                  value={analytics?.calls || 0}
                  caption="Persisted call records"
                />
                <Stat
                  icon={Activity}
                  title="Audio response P95"
                  value={
                    analytics?.metrics.audio_response_seconds
                      ? `${analytics.metrics.audio_response_seconds.p95.toFixed(2)}s`
                      : "—"
                  }
                  caption="Browser audio-energy estimate"
                />
                <Stat
                  icon={Clock3}
                  title="Tool latency P95"
                  value={
                    analytics?.metrics.tool_latency_seconds
                      ? `${analytics.metrics.tool_latency_seconds.p95.toFixed(2)}s`
                      : "—"
                  }
                  caption="Bounded backend requests"
                />
              </div>
              <div className="card">
                <h3>Recorded measurements</h3>
                <p className="muted">
                  Audio estimates use speech energy timestamps. Transcript
                  delivery time is excluded. Unclassified turns are not treated
                  as no-tool turns.
                </p>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Metric</th>
                        <th>Samples</th>
                        <th>Mean</th>
                        <th>P95</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(analytics?.metrics || {}).map(
                        ([name, m]) => (
                          <tr key={name}>
                            <td>{label(name)}</td>
                            <td>{m.count}</td>
                            <td>{m.mean.toFixed(3)}</td>
                            <td>{m.p95.toFixed(3)}</td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
                {!Object.keys(analytics?.metrics || {}).length && (
                  <Empty>
                    Measurements appear after a connected voice call.
                  </Empty>
                )}
              </div>
            </>
          )}
          <footer className="page-footer">
            <span>northstar support</span>
            <span>
              <ShieldCheck size={12} /> Demo store · Simulated payments
            </span>
          </footer>
        </main>
      </div>
      {connection && (
        <aside className="call-panel" aria-label="Active voice call">
          <div className="panel-header">
            <div>
              <p className="eyebrow">
                {staff ? "HUMAN TAKEOVER" : "YOUR CONVERSATION"}
              </p>
              <h3>{staff ? "Live support" : "Mira is here to help."}</h3>
            </div>
            <span className="ai-pill">{staff ? "LIVE" : "VOICE AI"}</span>
          </div>
          <VoiceRoom
            key={connection.token}
            connection={connection}
            staff={staff}
            onEnd={endCall}
          />
          {detail && (
            <CallBody detail={detail} staff={staff} busy={busy} run={run} />
          )}
        </aside>
      )}
      {!connection && reviewId && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Call details"
          >
            <div className="panel-header">
              <h2>Conversation details</h2>
              <button
                className="icon-button"
                aria-label="Close call details"
                onClick={() => {
                  setReviewId(null);
                  setDetail(null);
                }}
              >
                <X />
              </button>
            </div>
            {detail?.call.id === reviewId ? (
              <>
                <Badge status={detail.call.status} />
                <p>
                  {detail.call.summary ||
                    "Summary will be saved when the call ends."}
                </p>
                <CallBody detail={detail} staff={staff} busy={busy} run={run} />
              </>
            ) : (
              <p>Loading conversation…</p>
            )}
          </section>
        </div>
      )}
      {customer && (
        <div className="modal-backdrop">
          <section
            className="modal wide"
            role="dialog"
            aria-modal="true"
            aria-label="Customer profile"
          >
            <div className="panel-header">
              <div>
                <p className="eyebrow">CUSTOMER PROFILE</p>
                <h2>{customer.name}</h2>
              </div>
              <button
                className="icon-button"
                aria-label="Close profile"
                onClick={() => setCustomer(null)}
              >
                <X />
              </button>
            </div>
            <p className="muted">{customer.email}</p>
            <label>
              CRM notes
              <textarea
                value={customer.notes}
                onChange={(e) =>
                  setCustomer({ ...customer, notes: e.target.value })
                }
              />
            </label>
            <label>
              Preferred language
              <select
                value={customer.preferred_language}
                onChange={(e) =>
                  setCustomer({
                    ...customer,
                    preferred_language: e.target.value as Language,
                  })
                }
              >
                <option value="en">English</option>
                <option value="hi">Hindi</option>
              </select>
            </label>
            <button
              className="primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await api(`/staff/customers/${customer.id}`, "PATCH", {
                    notes: customer.notes,
                    preferred_language: customer.preferred_language,
                  });
                  setNotice("Customer record updated.");
                })
              }
            >
              Save profile
            </button>
            <OrderTable orders={customerOrders} />
          </section>
        </div>
      )}
    </div>
  );
}

function Login({
  onLogin,
}: {
  onLogin: (email: string, password: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("aarav@example.com"),
    [password, setPassword] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <main className="login-page">
      <div className="login-story">
        <a href="/" className="brand">
          <span className="brand-mark">
            <AudioLines />
          </span>
          northstar.
        </a>
        <span className="hero-chip">CUSTOMER CARE, WITH A HUMAN TOUCH</span>
        <h1>
          A little clarity.
          <br />A lot less waiting.
        </h1>
        <p>
          Meet support that listens. Talk through your orders, returns, and
          everything in between.
        </p>
        <div className="login-wave" aria-hidden="true">
          {[22, 45, 67, 36, 83, 55, 99, 61, 34, 73, 46, 24].map((h, i) => (
            <i style={{ height: h }} key={i} />
          ))}
        </div>
        <div className="login-note">
          <ShieldCheck size={18} /> Your account. Your conversation.
        </div>
      </div>
      <section className="login-form">
        <div className="login-top">
          REAL-TIME SUPPORT PLATFORM <span>01 / WELCOME</span>
        </div>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              await onLogin(email, password);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <p className="eyebrow">COME ON IN</p>
          <h2>Good to see you.</h2>
          <p className="muted">
            Sign in to your customer portal or support workspace.
          </p>
          <label>
            Email address
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              placeholder="Enter your password"
            />
          </label>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <button className="primary full" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
            <ArrowRight size={17} />
          </button>
          <div className="demo-accounts">
            <span className="eyebrow">DEMO ACCOUNTS</span>
            <div>
              <button
                type="button"
                onClick={() => {
                  setEmail("aarav@example.com");
                  setPassword("Demo-support-2026!");
                }}
              >
                Customer <ArrowUpRight size={13} />
              </button>
              <button
                type="button"
                onClick={() => {
                  setEmail("support@example.com");
                  setPassword("Demo-support-2026!");
                }}
              >
                Support staff <ArrowUpRight size={13} />
              </button>
            </div>
            <p>Seeded demo data · No real payments</p>
          </div>
        </form>
        <footer>Built for conversations that get somewhere.</footer>
      </section>
    </main>
  );
}
function Stat({
  icon: Icon,
  title,
  value,
  caption,
}: {
  icon: typeof Package;
  title: string;
  value: string | number;
  caption: string;
}) {
  return (
    <div className="stat">
      <span className="stat-icon">
        <Icon size={18} />
      </span>
      <div>
        <span className="small muted">{title}</span>
        <strong>{value}</strong>
        <span className="small muted">{caption}</span>
      </div>
    </div>
  );
}
function OrderTable({
  orders,
  expanded = false,
}: {
  orders: Order[];
  expanded?: boolean;
}) {
  return (
    <div className="table-card">
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Order / product</th>
              <th>Status</th>
              <th>Total</th>
              <th>Support status</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td>
                  <div className="product-cell">
                    <span className="product-icon">
                      <Package size={22} />
                    </span>
                    <div>
                      <strong>
                        {o.items.map((i) => i.product.name).join(", ")}
                      </strong>
                      <span className="small muted">
                        {o.id}
                        {o.delivered_at
                          ? ` · Delivered ${date(o.delivered_at)}`
                          : " · On its way"}
                      </span>
                      {expanded && (
                        <span className="small muted">
                          {o.return_eligibility.reason}
                        </span>
                      )}
                    </div>
                  </div>
                </td>
                <td>
                  <Badge status={o.status} />
                </td>
                <td className="price">{money(o.total_paise)}</td>
                <td>
                  {o.refund ? (
                    <div className="support-state">
                      <span className="small muted">Refund</span>
                      <Badge status={o.refund.status} />
                    </div>
                  ) : o.return ? (
                    <Badge status={`return_${o.return.status}`} />
                  ) : (
                    <span className="small muted">No requests</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!orders.length && <Empty>No orders to show.</Empty>}
    </div>
  );
}
function TicketCard({
  ticket,
  onSave,
}: {
  ticket: Ticket;
  onSave?: (status: string, notes: string) => void;
}) {
  const [status, setStatus] = useState(ticket.status),
    [notes, setNotes] = useState(ticket.notes);
  return (
    <article className="card ticket">
      <div className="card-top">
        <span className="small muted">#{ticket.id.slice(0, 8)}</span>
        <Badge status={ticket.status} />
      </div>
      <h3>{ticket.title}</h3>
      <p>{ticket.description}</p>
      {ticket.notes && (
        <p className="small muted">Support note: {ticket.notes}</p>
      )}
      {onSave && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSave(status, notes);
          }}
        >
          <label>
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="open">Open</option>
              <option value="in_progress">In progress</option>
              <option value="resolved">Resolved</option>
            </select>
          </label>
          <label>
            Resolution notes
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              maxLength={5000}
            />
          </label>
          <button className="secondary">Assign to me & save</button>
        </form>
      )}
    </article>
  );
}
function Refunds({
  dashboard,
  busy,
  run,
}: {
  dashboard: Dashboard;
  busy: boolean;
  run: (fn: () => Promise<void>) => void;
}) {
  const [reasons, setReasons] = useState<Record<string, string>>({});
  return (
    <div className="card">
      {dashboard.refunds.map((r) => (
        <div className="refund-row" key={r.id}>
          <div>
            <strong>
              {r.order_id}{" "}
              <span className="price">{money(r.amount_paise)}</span>
            </strong>
            <p className="small muted">{r.reason}</p>
            {r.decision_reason && (
              <p className="small muted">Decision: {r.decision_reason}</p>
            )}
          </div>
          <Badge status={r.status} />
          {r.status === "pending_approval" && (
            <div className="approval-controls">
              <input
                aria-label={`Decision reason for ${r.order_id}`}
                placeholder="Required decision reason"
                value={reasons[r.id] || ""}
                onChange={(e) =>
                  setReasons({ ...reasons, [r.id]: e.target.value })
                }
              />
              {["approve", "reject"].map((decision) => (
                <button
                  className={decision === "approve" ? "primary" : "secondary"}
                  key={decision}
                  disabled={busy || (reasons[r.id] || "").trim().length < 3}
                  onClick={() =>
                    run(async () => {
                      await api(`/staff/refunds/${r.id}/decision`, "POST", {
                        decision,
                        reason: reasons[r.id],
                      });
                    })
                  }
                >
                  {decision === "approve" ? "Approve" : "Reject"}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
      {!dashboard.refunds.length && <Empty>No refund requests.</Empty>}
    </div>
  );
}
function CallTable({
  calls,
  onReview,
  onEnd,
}: {
  calls: Portal["calls"];
  onReview: (id: string) => void;
  onEnd?: (id: string) => void;
}) {
  return (
    <div className="card">
      {calls.map((c) => (
        <div className="list-row" key={c.id}>
          <Phone size={17} />
          <div className="grow">
            <strong>
              {date(c.created_at)} · {c.language === "hi" ? "Hindi" : "English"}
            </strong>
            <p className="small muted">{c.summary || c.id.slice(0, 8)}</p>
          </div>
          <Badge status={c.status} />
          <button className="text-button" onClick={() => onReview(c.id)}>
            Review <ArrowUpRight size={14} />
          </button>
          {onEnd && !["ended", "failed"].includes(c.status) && (
            <button className="secondary" onClick={() => onEnd(c.id)}>
              End
            </button>
          )}
        </div>
      ))}
      {!calls.length && <Empty>Your conversations will appear here.</Empty>}
    </div>
  );
}
function CallBody({
  detail,
  staff,
  busy,
  run,
}: {
  detail: CallDetail;
  staff: boolean;
  busy: boolean;
  run: (fn: () => Promise<void>) => void;
}) {
  const [challenge, setChallenge] = useState<{
      challenge_id: string;
      demo_code: string;
    } | null>(null),
    [code, setCode] = useState("");
  return (
    <div className="call-body">
      {detail.call.status === "failed" && (
        <p role="alert" className="error">
          The voice agent disconnected. End this call and try again.
        </p>
      )}
      {detail.escalation && (
        <div className="handoff-banner">
          <Headphones size={15} />
          <span>
            Human support: {label(detail.escalation.status)}
            {detail.escalation.status === "active" &&
            !detail.escalation.representative_connected
              ? " · Representative reconnecting"
              : ""}
          </span>
        </div>
      )}
      {!staff && ["active", "connecting"].includes(detail.call.status) && (
        <div className="verification">
          <div>
            <ShieldCheck size={17} />
            <strong>
              {detail.verified
                ? "Identity verified for one action"
                : "Verify before an action"}
            </strong>
          </div>
          {!detail.verified && (
            <>
              {!challenge ? (
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      setChallenge(
                        await api(
                          `/calls/${detail.call.id}/verification`,
                          "POST",
                          {},
                        ),
                      );
                    })
                  }
                >
                  Verify identity
                </button>
              ) : (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      await api(
                        `/calls/${detail.call.id}/verification/complete`,
                        "POST",
                        { challenge_id: challenge.challenge_id, code },
                      );
                      setChallenge(null);
                      setCode("");
                    });
                  }}
                >
                  <p className="small muted">
                    Demo challenge: <strong>{challenge.demo_code}</strong>.
                    Enter it here, not over voice. Expires in 2 minutes.
                  </p>
                  <input
                    aria-label="Verification code"
                    inputMode="numeric"
                    pattern="[0-9]{6}"
                    maxLength={6}
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                  <button className="secondary" disabled={busy}>
                    Verify code
                  </button>
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setChallenge(null)}
                  >
                    New challenge
                  </button>
                </form>
              )}
            </>
          )}
        </div>
      )}
      {detail.actions
        .filter((a) => a.status === "pending" || a.status === "completed")
        .map((a) => (
          <div className="proposed-action" key={a.id}>
            <div>
              <span className="eyebrow">
                {a.status === "completed"
                  ? "COMPLETED"
                  : "YOUR CONFIRMATION NEEDED"}
              </span>
              <h4>{label(a.kind)} request</h4>
            </div>
            {Object.entries(a.payload).map(([k, v]) => (
              <p className="small" key={k}>
                <span className="muted">{label(k)}: </span>
                {v}
              </p>
            ))}
            {a.kind === "refund" && (
              <p className="small muted">
                This submits a request for human approval. It does not issue a
                payment.
              </p>
            )}
            {a.status === "pending" && !staff && (
              <div className="card-actions">
                <button
                  className="primary"
                  disabled={
                    busy || !detail.verified || a.expires_at < Date.now() / 1000
                  }
                  onClick={() =>
                    run(async () => {
                      await api(
                        `/calls/${detail.call.id}/actions/${a.id}/confirm`,
                        "POST",
                        {},
                      );
                    })
                  }
                >
                  <Check size={15} /> Confirm this action
                </button>
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() =>
                    run(async () => {
                      await api(
                        `/calls/${detail.call.id}/actions/${a.id}/cancel`,
                        "POST",
                        {},
                      );
                    })
                  }
                >
                  Dismiss
                </button>
              </div>
            )}
            {a.status === "completed" && (
              <Badge status={a.result?.status || a.status} />
            )}
          </div>
        ))}
      <div className="transcript-heading">
        <h4>Conversation</h4>
        <span className="small muted">Transcripts as available</span>
      </div>
      <div className="transcript" aria-live="polite">
        {detail.transcripts.map((t) => (
          <div className={`transcript-turn ${t.role}`} key={t.id}>
            <span>{t.role === "user" ? "CUSTOMER" : "MIRA"}</span>
            <p>{t.text}</p>
            {t.interrupted && <small>Interrupted</small>}
          </div>
        ))}
        {!detail.transcripts.length && (
          <Empty>
            Your conversation will appear here as transcripts arrive.
          </Empty>
        )}
      </div>
    </div>
  );
}
